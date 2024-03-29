#!/bin/bash

BACKEND_DOMAIN=$(/opt/elasticbeanstalk/bin/get-config environment -k BACKEND_DOMAIN)
ORIGINAL_FILE=/var/app/staging/.platform/nginx/nginx.conf
TMP_FILE=$(mktemp)

cp --attributes-only --preserve $ORIGINAL_FILE $TMP_FILE
cat $ORIGINAL_FILE | envsubst "\$BACKEND_DOMAIN" > $TMP_FILE && mv $TMP_FILE $ORIGINAL_FILE
