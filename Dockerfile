FROM python:3.7

ENV PYTHONPATH=/srv
WORKDIR /srv

COPY ./requirements.txt /tmp
RUN pip install -r /tmp/requirements.txt

CMD gunicorn ruqqus.__main__:app -b 0.0.0.0 -w 3 -k gevent --worker-connections 6 --preload --max-requests 5000 --max-requests-jitter 500

COPY . /srv
