#!/usr/bin/env python

import os
import sys
import json
import time
import logging
import subprocess

import kazoo
from kazoo.client import KazooClient

logging.basicConfig(
    level   = logging.INFO,
    stream  = sys.stdout,
    datefmt = "%Y-%m-%d %H:%M:%S",
    format  = "[%(levelname)s %(asctime)s %(filename)s %(lineno)s] %(message)s"
)

LOG = logging.getLogger(__name__)

class mock_pub(object):

    _root_node   = ''
    _server_list = {}
    _zookeeper   = None
    _shell_path  = ''

    def __init__(self, host = '127.0.0.1', port = 2181, root_node = '/test', shell_path = './'):
        self._zookeeper  = KazooClient('%s:%s' % (host, port,))
        self._root_node  = root_node
        self._shell_path = shell_path

    def run(self):
        self._zookeeper.start()
        self.init()

    def init(self):
        pub_node = '%s/to_pub_notice' % self._root_node
        default_node_value = json.dumps({'update_time' : time.time()})

        try:
            if self._zookeeper.exists(pub_node) is None:
                self._zookeeper.create(pub_node, default_node_value, makepath = True)
        except kazoo.exceptions.NodeExistsError:
            pass

        @self._zookeeper.ChildrenWatch('%s/server_list' % (self._root_node, ))
        def server(server_list):
            for server_node in server_list:
                result = self.init_server(server_node)
                LOG.info('refresh server list %s' % json.dumps(result))

        @self._zookeeper.ChildrenWatch('%s/to_pub_notice' % (self._root_node, ))
        def to_pub_node(pub_node_list):
            for pub_node_id in pub_node_list:
                LOG.info('watch_pub children %s/to_pub_notice/%s' % (self._root_node, pub_node_id, ))
                self.to_pub(pub_node_id)

        return self

    def init_server(self, server_node):
        server_detail = self._zookeeper.get('%s/server_list/%s' % (self._root_node, server_node, ))
        if 0 == len(server_detail[0]):
            self._server_list[server_node] = {'server_id' : 0, 'server_name' : '', 'update_time' : 0}
        else:
            self._server_list[server_node] = json.loads(server_detail[0])

        return self._server_list[server_node]

    def to_pub(self, pub_node_id):

        @self._zookeeper.DataWatch('%s/to_pub_notice/%s' % (self._root_node, pub_node_id, ))
        def to_zip_execute(data, stat, event):
            if event is not None and event.type == 'DELETED':
                return

            if 0 == len(data):
                return

            LOG.info('watch_pub execute %s/to_pub_notice/%s %s' % (self._root_node, pub_node_id, data, ))

            node_detail = json.loads(data)
            if node_detail.get('status', None) == 'ok' or \
                            node_detail.get('status', None) == 'failed' or \
                            node_detail.get('servers', None) is None:
                return

            all_pub_finished = True

            for server_index in self._server_list:
                if 0 == self._server_list[server_index]['server_id'] or \
                            str(self._server_list[server_index]['server_id']) not in node_detail['servers']:
                    continue

                node_value = {
                    'update_time' : time.time()
                }

                if self.pub_execute(node_detail['config_version'], node_detail['game_version'], self._server_list[server_index]['server_id']) is True:
                    LOG.info('pub node %s/to_pub_result/%s/s%s pub success' % (self._root_node, pub_node_id, self._server_list[server_index]['server_id'] ))
                    node_value['status'] = 'ok'
                else:
                    LOG.info('pub node %s/to_pub_result/%s/s%s pub failed' % (self._root_node, pub_node_id, self._server_list[server_index]['server_id'] ))
                    node_value['status'] = 'failed'
                    all_pub_finished     = False

                pub_server_node = '%s/to_pub_result/%s/s%s' % (self._root_node, pub_node_id, self._server_list[server_index]['server_id'], )

                try:
                    if self._zookeeper.exists(pub_server_node) is None:
                        self._zookeeper.create(pub_server_node, json.dumps(node_value), makepath = True)
                    else:
                        self._zookeeper.set(pub_server_node, json.dumps(node_value))
                except kazoo.exceptions.NodeExistsError:
                    pass

            if all_pub_finished:
                node_detail['status']      = 'ok'
                node_detail['finish_time'] = time.time()
                self._zookeeper.set('%s/to_pub_notice/%s' % (self._root_node, pub_node_id, ), json.dumps(node_detail))

    def pub_execute(self, config_version, game_version, server_id):
        '''
        to execute shell to zip resource
        '''

        LOG.info('start to execute shell %s/pub.sh %s %s %s' % (self._shell_path, config_version, game_version, server_id, ))
        result = subprocess.call('%s/pub.sh %s %s %s > /dev/null 2>&1' % (self._shell_path, config_version, game_version, server_id, ), shell = True)

        return True if result == 0 else False

if __name__ == '__main__':
    os.environ['TZ'] = 'Asia/Shanghai'
    time.tzset()

    m = mock_pub(
        sys.argv[1] if len(sys.argv) >= 2 else '127.0.0.1',
        sys.argv[2] if len(sys.argv) >= 3 else '2181',
        sys.argv[3] if len(sys.argv) >= 4 else '/test',
        os.path.dirname(sys.argv[0])
    )
    m.run()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass