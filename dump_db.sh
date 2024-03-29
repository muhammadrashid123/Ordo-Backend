#!/bin/bash

source dump_db.env

ssh -i ${KEY_FILE_PATH} "${USERNAME}@${IP_ADDRESS}" "pg_dump -v --no-owner --no-acl  postgresql://${POSTGRES_USERNAME}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB} | zstd" > init.sql.zstd
zstdcat init.sql.zstd > init.sql
