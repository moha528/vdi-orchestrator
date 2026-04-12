#!/bin/sh
# Inject json-secret-key then delegate to the base image's startup

mkdir -p /etc/guacamole

if [ -n "$GUAC_JSON_SECRET" ]; then
    echo "json-secret-key: $GUAC_JSON_SECRET" >> /etc/guacamole/guacamole.properties
fi

# Delegate to the original entrypoint
exec /opt/guacamole/bin/entrypoint.sh "$@"
