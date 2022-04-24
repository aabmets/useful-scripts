# ================================================================================== #
#                                                                                    #
#   MIT License                                                                      #
#                                                                                    #
#   Copyright (c) 2022 Mattias Aabmets                                               #
#                                                                                    #
#   Permission is hereby granted, free of charge, to any person obtaining a copy     #
#   of this software and associated documentation files (the "Software"), to deal    #
#   in the Software without restriction, including without limitation the rights     #
#   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell        #
#   copies of the Software, and to permit persons to whom the Software is            #
#   furnished to do so, subject to the following conditions:                         #
#                                                                                    #
#   The above copyright notice and this permission notice shall be included in all   #
#   copies or substantial portions of the Software.                                  #
#                                                                                    #
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR       #
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,         #
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE      #
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER           #
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,    #
#   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE    #
#   SOFTWARE.                                                                        #
#                                                                                    #
# ================================================================================== #
from argparse import ArgumentParser
from threading import Thread
from queue import Queue
from datetime import datetime
import mysql.connector as mysql


# ================================================================================== #
zero_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
workload = Queue()
results = Queue()
max_workers = 10
workers = list()
dry_run = bool()
db_names_like = list()
db_config = dict(
    user='admin',
    password='admin'
)


# ================================================================================== #
def parse_runtime_args() -> None:
    parser = ArgumentParser()
    parser.add_argument('db_names_like', nargs='+', default=None)
    parser.add_argument('-n', '--dry_run', action='store_true', default=False)
    parser.add_argument('-x', '--host', required=True)
    args = parser.parse_args()

    global dry_run
    dry_run = args.dry_run

    global db_names_like
    db_names_like = args.db_names_like

    global db_config
    db_config['host'] = args.host


# ---------------------------------------------------------------------------------  #
def create_workload() -> None:
    with mysql.connect(**db_config) as cnx:
        with cnx.cursor(buffered=True) as cursor:
            for db_nl in db_names_like:
                cursor.execute(f'SHOW DATABASES LIKE \'{db_nl}\'')
                for db in cursor.fetchall():
                    workload.put(db)


# ---------------------------------------------------------------------------------  #
def create_workers() -> None:
    while True:
        _worker = Thread(target=work_func)
        workers.append(_worker)
        if (
                len(workers) == len(workload.queue) or
                len(workers) == max_workers
        ):
            break


# ---------------------------------------------------------------------------------  #
def work_func() -> None:
    with mysql.connect(**db_config) as cnx:
        with cnx.cursor(buffered=True) as cursor:
            successes, failures = 0, 0
            while bool(workload.queue):
                db = workload.get()
                cursor.execute(f'USE {db[0]}')
                cursor.execute('SHOW TABLES')
                for table in cursor.fetchall():
                    cursor.execute(f'OPTIMIZE TABLE {table[0]}')
                    response = cursor.fetchall()
                    print(response)
                    if response[1][-1] == 'OK':
                        successes += 1
                    else:
                        failures += 1
                workload.task_done()
            results.put({
                'successes': successes,
                'failures': failures
            })


# ================================================================================== #
if __name__ == '__main__':
    parse_runtime_args()
    create_workload()
    create_workers()

    start_time = datetime.now()
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    end_time = datetime.now()

    diff = end_time - start_time
    time_taken = zero_time + diff
    while not results.empty():
        res = results.get()
        print(res)
        results.task_done()
    print(f'Time taken: {time_taken}.')
