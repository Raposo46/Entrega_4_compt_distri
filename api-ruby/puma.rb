# Servidor Puma: WORKERS processos x THREADS threads (mesma concorrência da versão
# Python/Gunicorn, para a comparação entre linguagens ser justa).
workers Integer(ENV.fetch("WORKERS", "2"))
threads Integer(ENV.fetch("THREADS", "8")), Integer(ENV.fetch("THREADS", "8"))
bind "tcp://0.0.0.0:5000"
environment "production"
# Sem preload_app: cada worker carrega o app (e abre a sua conexão com o Redis) sozinho

