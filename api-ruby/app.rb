# frozen_string_literal: true

# Serviço de API do Link Extractor - versão Ruby (Sinatra + Puma + Nokogiri + Redis opcional).
#
# Baseado na etapa step6 do repositório oficial ibnesayeed/linkextractor:
#   GET /               -> mensagem de uso
#   GET /api/<url>      -> lista JSON [{"text": ..., "href": ...}] dos links de <url>
#   GET /api?url=<url>  -> mesma operação recebendo a URL via query string
#   GET /health         -> verificação de saúde (usada pelo Docker Compose e orquestrador)
#
# Variáveis de ambiente: CACHE_ENABLED, REDIS_URL, CACHE_TTL, CONNECT_TIMEOUT, REQUEST_TIMEOUT.

require "sinatra/base"
require "json"
require "net/http"
require "uri"
require "nokogiri"
require "redis"

CACHE_ENABLED = %w[1 true yes sim].include?(ENV.fetch("CACHE_ENABLED", "false").strip.downcase)
REDIS_URL = ENV.fetch("REDIS_URL", "redis://redis:6379/0")
CACHE_TTL = Integer(ENV.fetch("CACHE_TTL", "3600"))
CONNECT_TIMEOUT = Float(ENV.fetch("CONNECT_TIMEOUT", "3"))
REQUEST_TIMEOUT = Float(ENV.fetch("REQUEST_TIMEOUT", "5"))
MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
USER_AGENT = "Mozilla/5.0 (compatible; LinkExtractor-T4/1.0; +https://github.com/ibnesayeed/linkextractor)"

class ErroExtracao < StandardError
  attr_reader :status

  def initialize(status, mensagem)
    super(mensagem)
    @status = status
  end
end

class LinkExtractor < Sinatra::Base
  set :environment, :production
  set :logging, false
  set :show_exceptions, false
  set :raise_errors, false
  disable :protection

  GUARDA_LOCKS = Mutex.new
  LOCKS_POR_CHAVE = {}

  def self.lock_chave(chave)
    GUARDA_LOCKS.synchronize { LOCKS_POR_CHAVE[chave] ||= Mutex.new }
  end

  # Uma conexão Redis por thread do Puma (equivalente ao ConnectionPool por thread do redis-py)
  def self.cache
    return nil unless CACHE_ENABLED

    Thread.current[:le_redis] ||= Redis.new(
      url: REDIS_URL,
      connect_timeout: 1.5,
      read_timeout: 1.5,
      write_timeout: 1.5
    )
  end

  helpers do
    def normalizar_url(url)
      url = url.to_s.strip.sub(%r{\A(https?):/+}i, '\1://')
      url = "http://#{url}" unless url =~ %r{\Ahttps?://}i
      uri = URI.parse(url)
      raise ErroExtracao.new(400, "URL inválida") if uri.host.nil? || uri.host.empty?

      url
    rescue URI::InvalidURIError
      raise ErroExtracao.new(400, "URL inválida")
    end

    def baixar(url)
      uri = URI.parse(url)
      (MAX_REDIRECTS + 1).times do
        http = Net::HTTP.new(uri.host, uri.port)
        http.use_ssl = (uri.scheme == "https")
        http.open_timeout = CONNECT_TIMEOUT
        http.read_timeout = REQUEST_TIMEOUT
        http.write_timeout = REQUEST_TIMEOUT
        requisicao = Net::HTTP::Get.new(uri.request_uri, "User-Agent" => USER_AGENT)

        corpo = +""
        resposta = nil
        http.start do |conexao|
          conexao.request(requisicao) do |r|
            resposta = r
            next unless r.is_a?(Net::HTTPSuccess)

            r.read_body do |pedaco|
              corpo << pedaco
              raise ErroExtracao.new(502, "página excede o limite de 5 MB") if corpo.bytesize > MAX_BYTES
            end
          end
        end

        case resposta
        when Net::HTTPSuccess
          return [corpo, uri]
        when Net::HTTPRedirection
          raise ErroExtracao.new(502, "redirecionamento sem Location") if resposta["location"].to_s.empty?

          uri = URI.join(uri.to_s, resposta["location"])
        else
          raise ErroExtracao.new(502, "site de origem respondeu HTTP #{resposta.code}")
        end
      end
      raise ErroExtracao.new(502, "redirecionamentos demais")
    rescue Net::OpenTimeout, Net::ReadTimeout, Net::WriteTimeout
      raise ErroExtracao.new(504, "timeout ao acessar o site de origem")
    rescue SocketError, SystemCallError, OpenSSL::SSL::SSLError, EOFError, IOError, URI::InvalidURIError => e
      raise ErroExtracao.new(502, "falha ao acessar o site de origem: #{e.class}")
    end

    def extract_links(url)
      corpo, base_uri = baixar(url)
      doc = Nokogiri::HTML(corpo)
      base_str = base_uri.to_s
      if (tag_base = doc.at_css("base[href]"))
        href_base = tag_base["href"].to_s.strip
        unless href_base.empty?
          begin
            base_str = URI.join(base_str, href_base).to_s
          rescue URI::Error
            # mantém base_str original se <base> for malformada
          end
        end
      end

      links = []
      doc.css("a[href]").each do |tag|
        href = tag["href"].to_s.strip
        next if href.empty? || href.start_with?("javascript:", "mailto:", "tel:")

        begin
          absoluto = URI.join(base_str, href)
        rescue URI::Error
          next
        end
        next unless %w[http https].include?(absoluto.scheme)

        texto = tag.text.strip.split.join(" ")
        links << {
          text: texto.empty? ? "[IMG]" : texto,
          href: absoluto.to_s
        }
      end
      links
    end

    def obter_links(url)
      cache = LinkExtractor.cache
      return [extract_links(url).to_json, "BYPASS"] if cache.nil?

      chave = "links:#{url}"
      begin
        guardado = cache.get(chave)
        return [guardado, "HIT"] unless guardado.nil?
      rescue Redis::BaseError => e
        warn "Redis indisponível na leitura (#{e.class}); extraindo sem cache"
        return [extract_links(url).to_json, "BYPASS"]
      end

      # Coalescência de cache miss (evita thundering herd quando múltiplas threads pedem a mesma URL fria)
      LinkExtractor.lock_chave(chave).synchronize do
        begin
          guardado = cache.get(chave)
          return [guardado, "HIT"] unless guardado.nil?
        rescue Redis::BaseError
          # segue para extração
        end

        conteudo = extract_links(url).to_json
        begin
          cache.set(chave, conteudo, ex: CACHE_TTL)
        rescue Redis::BaseError => e
          warn "Redis indisponível na escrita (#{e.class})"
        end
        [conteudo, "MISS"]
      end
    end

    def responder_extracao(url)
      conteudo, origem = obter_links(normalizar_url(url))
      status 200
      content_type :json
      headers "X-Cache" => origem
      conteudo
    rescue ErroExtracao => e
      status e.status
      content_type :json
      { error: e.message, url: url }.to_json
    end
  end

  get "/" do
    "Usage: http://<hostname>[:<prt>]/api/<url>"
  end

  get "/api" do
    responder_extracao(params["url"])
  end

  get "/api/*" do
    url = params["splat"].first
    url += "?#{request.query_string}" unless request.query_string.empty?
    responder_extracao(url)
  end

  get "/health" do
    redis_ok = nil
    if (cache = LinkExtractor.cache)
      redis_ok = begin
        cache.ping == "PONG"
      rescue Redis::BaseError
        false
      end
    end
    content_type :json
    { status: "ok", linguagem: "ruby", cache: CACHE_ENABLED, redis: redis_ok }.to_json
  end
end
