FROM guacamole/guacamole:1.6.0

# Télécharger l'extension auth-json depuis les releases officielles Apache
USER root
RUN mkdir -p /etc/guacamole/extensions && \
    curl -fSL https://downloads.apache.org/guacamole/1.6.0/binary/guacamole-auth-json-1.6.0.tar.gz -o /tmp/auth-json.tar.gz && \
    tar -xzf /tmp/auth-json.tar.gz -C /tmp && \
    cp /tmp/guacamole-auth-json-1.6.0/guacamole-auth-json-1.6.0.jar /etc/guacamole/extensions/ && \
    rm -rf /tmp/auth-json.tar.gz /tmp/guacamole-auth-json-1.6.0 && \
    chown -R guacamole:guacamole /etc/guacamole
USER guacamole
