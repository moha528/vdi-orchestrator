#!/bin/sh
# Inject json-secret-key then delegate to the base image's startup

mkdir -p /etc/guacamole

if [ -n "$GUAC_JSON_SECRET" ]; then
    echo "json-secret-key: $GUAC_JSON_SECRET" >> /etc/guacamole/guacamole.properties
fi

# Find and exec the original startup script
if [ -x /opt/guacamole/bin/start.sh ]; then
    exec /opt/guacamole/bin/start.sh "$@"
elif [ -x /docker-entrypoint.sh ]; then
    exec /docker-entrypoint.sh "$@"
else
    # Fallback: deploy WAR manually + start Tomcat
    cp /opt/guacamole/guacamole.war /usr/local/tomcat/webapps/guacamole.war 2>/dev/null
    exec catalina.sh run
fi
