FROM postgres:12-alpine

# Copy initialization scripts, prepending a number for order of execution.
COPY ./schema.sql /docker-entrypoint-initdb.d/00_schema.sql
COPY ./dev_data.sql /docker-entrypoint-initdb.d/01_dev_data.sql
