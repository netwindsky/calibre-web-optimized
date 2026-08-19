FROM linuxserver/calibre-web:latest

WORKDIR /app/calibre-web

COPY requirements.txt .
RUN /lsiopy/bin/pip install --no-cache-dir -r requirements.txt

COPY cps/ cps/
COPY cps/static/ cps/static/
COPY cps/templates/ cps/templates/
COPY cps/metadata_provider/ cps/metadata_provider/
COPY generate_thumbnails.py .

RUN cat /etc/s6-overlay/s6-rc.d/init-calibre-web-config/run | \
    sed 's|lsiown -R abc:abc|#lsiown -R abc:abc|g' | \
    sed 's|    /config \\|#/config \\|g' | \
    sed 's|    /app/calibre-web/cps/cache|#/app/calibre-web/cps/cache|g' \
    > /tmp/init-run && \
    mv /tmp/init-run /etc/s6-overlay/s6-rc.d/init-calibre-web-config/run && \
    echo '' >> /etc/s6-overlay/s6-rc.d/init-calibre-web-config/run && \
    echo '# Fast permissions: only chown specific files, not recursive on 279k thumbnails' >> /etc/s6-overlay/s6-rc.d/init-calibre-web-config/run && \
    echo 'chown abc:abc /config /app/calibre-web/cps/cache /app/calibre-web/cps/cache/thumbnails 2>/dev/null' >> /etc/s6-overlay/s6-rc.d/init-calibre-web-config/run && \
    echo 'chown abc:abc /config/app.db /config/app.db-wal /config/app.db-shm /config/calibre-web.log 2>/dev/null || true' >> /etc/s6-overlay/s6-rc.d/init-calibre-web-config/run && \
    echo 'exit 0' >> /etc/s6-overlay/s6-rc.d/init-calibre-web-config/run && \
    chmod +x /etc/s6-overlay/s6-rc.d/init-calibre-web-config/run

RUN echo '#!/usr/bin/with-contenv bash' > /etc/s6-overlay/s6-rc.d/svc-calibre-web/run && \
    echo 'export CALIBRE_DBPATH=/config' >> /etc/s6-overlay/s6-rc.d/svc-calibre-web/run && \
    echo 'cd /app/calibre-web' >> /etc/s6-overlay/s6-rc.d/svc-calibre-web/run && \
    echo 'exec s6-setuidgid abc python3 /app/calibre-web/cps.py' >> /etc/s6-overlay/s6-rc.d/svc-calibre-web/run && \
    chmod +x /etc/s6-overlay/s6-rc.d/svc-calibre-web/run

ENV CALIBRE_PORT=8083
ENV CALIBRE_DBPATH=/config
