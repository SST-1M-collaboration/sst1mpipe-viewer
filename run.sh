if [  $# -le 0 ]
    then
        echo "Usage ./run.sh [/path/to/data/dir/]"
    exit 1
fi

if  $(pgrep bokeh >/dev/null)  ; then
    PID=$(pgrep bokeh)
    echo 'some bokeh sever is already running with PID ' $PID
    echo 'you may want to kill it first'
    read -p "Continue ? (y/n) " -n 1 -r
    if [[ ! $REPLY =~ ^[Yy]$ ]] ; then
        echo
        exit 1
    fi
fi
source ~/.bashrc
conda activate digicampipe
nohup bokeh serve sst_mon --allow-websocket-origin=calculus:8085 --allow-websocket-origin=localhost:8085 --port 8085 --args $1 &##1>log.log 2>err.log &

PID=$(pgrep bokeh)

if [ -z ${PID+x} ]; then echo "Some error occured"; else echo "Bokeh server running! PID =$PID"; fi
