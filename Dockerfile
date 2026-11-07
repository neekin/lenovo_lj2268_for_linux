ARG CUPS_IMAGE=anujdatar/cups:latest
FROM ${CUPS_IMAGE} AS builder
ARG DRIVER=python
USER root
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY . /src
RUN bash /src/install.sh --no-deps --driver "$DRIVER" --stage /driver

FROM ${CUPS_IMAGE}
USER root
COPY --from=builder /driver/rastertolkpl /usr/lib/cups/filter/rastertolkpl
COPY --from=builder /driver/libjbigwrap.so /usr/local/lib/libjbigwrap.so
COPY --from=builder /driver/ppd/Lenovo-LJ2268.ppd /usr/share/ppd/lenovo/Lenovo-LJ2268.ppd
COPY --from=builder /driver/ppd/Lenovo-LJ2268.ppd /usr/share/cups/model/Lenovo-LJ2268.ppd
COPY --from=builder /driver/usb/lenovo-lj2268-unidir /usr/share/cups/usb/lenovo-lj2268-unidir
# Keep the base image's entrypoint, user management and CUPS startup behavior.
CMD ["/bin/bash", "-e", "/entrypoint.sh"]
