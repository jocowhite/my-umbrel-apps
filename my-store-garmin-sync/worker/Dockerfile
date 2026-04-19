FROM thisisarpanghosh/garmin-fetch-data:latest

USER root

COPY entrypoint.sh /usr/local/bin/garmin-wrapper.sh
RUN chmod +x /usr/local/bin/garmin-wrapper.sh

USER 1000:1000

ENTRYPOINT ["/usr/local/bin/garmin-wrapper.sh"]
