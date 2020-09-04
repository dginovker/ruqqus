pip3 install -r ruqqus/requirements.txt
export PYTHONPATH=$PYTHONPATH:~/ruqqus
cd ~
source env.sh
newrelic-admin run-program gunicorn ruqqus.__main__:app -k gevent -w $WEB_CONCURRENCY --worker-connections $WORKER_CONNECTIONS --max-requests 10000 --max-requests-jitter 500 --preload