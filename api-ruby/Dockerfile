FROM ruby:3.3-slim

WORKDIR /app
COPY Gemfile ./
# build-essential: o Puma compila uma extensão em C durante o bundle install
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && bundle config set --local without 'development test' \
 && bundle install \
 && apt-get purge -y --auto-remove build-essential \
 && rm -rf /var/lib/apt/lists/*
COPY app.rb config.ru puma.rb ./

ENV WORKERS=2 THREADS=8 APP_ENV=production RACK_ENV=production
EXPOSE 5000

CMD ["bundle", "exec", "puma", "-C", "puma.rb"]

