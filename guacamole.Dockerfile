FROM guacamole/guacamole:1.6.0

# Télécharger l'extension auth-json depuis les releases officielles Apache
ADD https://downloads.apache.org/guacamole/1.6.0/binary/guacamole-auth-json-1.6.0.tar.gz /tmp/auth-json.tar.gz
RUN tar -xzf /tmp/auth-json.tar.gz -C /tmp && \
    cp /tmp/guacamole-auth-json-1.6.0/guacamole-auth-json-1.6.0.jar /etc/guacamole/extensions/ && \
    rm -rf /tmp/auth-json.tar.gz /tmp/guacamole-auth-json-1.6.0
