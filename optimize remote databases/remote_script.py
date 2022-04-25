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
from argparse import ArgumentParser, Namespace
from threading import Thread
from queue import Queue
from datetime import datetime
import mysql.connector as mysql


# ================================================================================== #
ZERO_TIME = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
MAX_WORKERS = 30
CONFIG = dict(
    user='admin',
    password='admin',
    connection_timeout=1,
    host='127.0.0.1',
    port=3306
)


# ================================================================================== #
class Optimizer:
    workload = Queue()
    results = Queue()
    workers = list()

    # ---------------------------------------------------------------------------------  #
    @classmethod
    def _worker(cls) -> None:
        """
        This method obtains database names from the workload Queue,
        tries to optimize as many tables as it can in each database,
        and saves the total work result into the results Queue.

        :return: None
        """
        with mysql.connect(**CONFIG) as cnx:
            with cnx.cursor(buffered=True) as cursor:
                successes, failures = 0, 0
                while bool(cls.workload.queue):
                    db = cls.workload.get()
                    cursor.execute(f'USE {db}')
                    cursor.execute('SHOW TABLES')
                    for table in cursor.fetchall():
                        cursor.execute(f'OPTIMIZE TABLE {table[0]}')
                        response = cursor.fetchall()
                        if response[1][-1] == 'OK':
                            successes += 1
                        else:
                            failures += 1
                    cls.workload.task_done()
                cls.results.put({
                    'sc': successes,
                    'fl': failures
                })

    # ---------------------------------------------------------------------------------- #
    @classmethod
    def init(cls) -> None:
        """
        This method inserts all found matching database
        names into the workload and creates the
        appropriate amount of worker threads.

        :return: None
        """
        for db in databases:
            cls.workload.put(db)
        while True:
            worker = Thread(target=cls._worker)
            cls.workers.append(worker)
            stop_cond = [
                len(cls.workers) == len(cls.workload.queue),
                len(cls.workers) == MAX_WORKERS
            ].count(True)
            if stop_cond:
                break

    # ---------------------------------------------------------------------------------  #
    @classmethod
    def run(cls) -> None:
        """
        This method runs all worker threads and then
        waits for them to finish processing.

        :return: None
        """
        for worker in cls.workers:
            worker.start()
        for worker in cls.workers:
            worker.join()

    # ---------------------------------------------------------------------------------  #
    @classmethod
    def get_results(cls) -> dict:
        """
        This method adds together all results in the
        results Queue and returns the results total.

        :return: Total results of all databases
        """
        successes, failures = 0, 0
        while bool(cls.results.queue):
            result = cls.results.get()
            successes += result['sc']
            failures += result['fl']
            cls.results.task_done()
        return dict(
            sc=successes,
            fl=failures
        )


# ================================================================================== #
def parse_cmdline_args() -> Namespace:
    """
    Obtains command line args passed to this script.

    :return: Namespace of args
    """
    parser = ArgumentParser()
    parser.add_argument('db_names_like', nargs='+', default=None)
    parser.add_argument('-n', '--dry_run', action='store_true', default=False)
    parser.add_argument('--host', required=True)
    return parser.parse_known_args()[0]


# ---------------------------------------------------------------------------------  #
def get_databases() -> list:
    """
    Asks the MySQL server for database names matching the cmdline LIKE regex args.

    :return: List of database names
    """
    dbs = list()
    with mysql.connect(**CONFIG) as cnx:
        with cnx.cursor(buffered=True) as cursor:
            for name in args.db_names_like:
                cursor.execute(f'SHOW DATABASES LIKE \'{name}\'')
                for db in cursor.fetchall():
                    dbs.append(db[0])
    return dbs


# ================================================================================== #
if __name__ == '__main__':
    args = parse_cmdline_args()
    try:
        databases = get_databases()
        #  get_databases() has to be inside the try block, because
        #  this is the first call that would raise an exception
        #  if the local MySQL database server should be offline.

        if args.dry_run:
            print(f'{args.host} - Host would try to optimize '
                  f'-{len(databases)}- databases.')
        else:
            start_time = datetime.now()
            Optimizer.init()
            Optimizer.run()
            end_time = datetime.now()

            diff = end_time - start_time
            time_taken = ZERO_TIME + diff

            results = Optimizer.get_results()
            print(f'{args.host} - Optimization result: '
                  f'{results["sc"]}/{results["fl"]} tables '
                  f'succeeded/failed. Time taken: '
                  f'{time_taken.minute} min : '
                  f'{time_taken.second} sec')

    except mysql.Error as err:
        print(f'{args.host} - ERROR! {err.msg}')
