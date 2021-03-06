#!/usr/bin/python
description="""
nuotop - a 'top' like interface for NuoDB. Requires a REST endpoint for the database.
"""

import argparse
import nuodbTools
import sys
import fcntl
import random
import termios
import time
import struct
from threading import Thread
import traceback
import curses

def assemble_databases(domain):
  rows = []
  mytime= time.time() * 1000
  try:
    databases = request(domain=domain, path="/databases")
    regions = request(domain=domain, path="/regions")
    commits = request(domain=domain, path="/domain/stats?metric=Commits&start=%d&stop=%d&breakdown=db" % (mytime-10000, mytime))
    connections = request(domain=domain, path="/domain/stats?metric=ClientCncts&start=%d&stop=%d&breakdown=db" % (mytime-10000, mytime))
  except:
    pass
  # assemble data structure
  processes = {}
  for region in regions:
    region_name = region['region']
    for host in region['hosts']:
      for process in host['processes']:
        if process['dbname'] not in processes:
          processes[process['dbname']] = {}
        if region_name not in processes[process['dbname']]:
          processes[process['dbname']][region_name] = {}
        if host['hostname'] not in processes[process['dbname']][region_name]:
          processes[process['dbname']][region_name][host['hostname']] = {"SM": 0, "TE":0}
        processes[process['dbname']][region_name][host['hostname']][process['type']] +=1
        
  rows.append([
               ("DATABASE", curses.A_REVERSE),
               ("STATUS", curses.A_REVERSE),
               ("#REG", curses.A_REVERSE),
               ("#SM", curses.A_REVERSE),
               ("#TE", curses.A_REVERSE),
               ("TEMPLATE", curses.A_REVERSE),
               ("#CMTS", curses.A_REVERSE),
               ("#CON", curses.A_REVERSE)
               ])
  for database in databases:
    row = []
    if database['active'] and database['ismet']:
      attr = curses.color_pair(1)
    elif database['active']:
      attr = curses.color_pair(2)
    else:
      attr = curses.color_pair(3)
    row.append((database['name'], attr))
    row.append(database['status'])
    row.append(str(len(processes[database['name']])))
    sm_count = 0
    te_count = 0
    for region in processes[database['name']]:
      for host in processes[database['name']][region]:
        sm_count += processes[database['name']][region][host]['SM']
        te_count += processes[database['name']][region][host]['TE']
    row.append(str(sm_count))
    row.append(str(te_count))
    row.append(database['template']['name'])
    if database['name'] in commits:
      row.append(average_metric(commits[database['name']], red_threshold=9999999999, yellow_threshold=9999999999, format="int"))
    else:
      row.append("?")
    if database['name'] in connections:
      row.append(latest_metric(connections[database['name']], red_threshold=9999999999, yellow_threshold=9999999999, format="int"))
    else:
      row.append("?")
    rows.append(row)
  return rows

def assemble_hosts(domain):
  rows = []
  mytime= time.time() * 1000
  regions = request(domain=domain, path="/regions")
  cpu = request(domain=domain, path="/domain/stats?metric=OS-cpuTotalTimePercent&start=%d&stop=%d&breakdown=host" % (mytime-10000, mytime))
  memory = request(domain=domain, path="/domain/stats?metric=OS-memUsedPercent&start=%d&stop=%d&breakdown=host" % (mytime-10000, mytime))
  conns = request(domain=domain, path="/domain/stats?metric=ClientCncts&start=%d&stop=%d&breakdown=host" % (mytime-10000, mytime))
  
  rows.append([
               ("HOSTNAME", curses.A_REVERSE), 
               ("REGION", curses.A_REVERSE), 
               ("IPADDR", curses.A_REVERSE), 
               ("PORT", curses.A_REVERSE), 
               ("#PRC", curses.A_REVERSE), 
               ("%CPU", curses.A_REVERSE), 
               ("%MEM", curses.A_REVERSE), 
               ("#CON", curses.A_REVERSE)
              ])
  for region in regions:
    region_name = region['region']
    for host in sorted(region['hosts'], key=lambda host: host['hostname']):
      row = []
      if host['isBroker']:
        row.append((host['hostname'], curses.color_pair(1)))
      else:
        row.append((host['hostname'], curses.A_BOLD))
      row.append(region_name)
      row.append((host['ipaddress'], curses.A_BOLD))
      row.append(str(host['port']))
      row.append((str(len(host['processes'])), curses.A_BOLD))
      if host['id'] in cpu:
        row.append(average_metric(cpu[host['id']]))
      else:
        row.append("?")
      if host['id'] in memory:
        row.append(average_metric(memory[host['id']]))
      else:
        row.append("?")
      if host['id'] in conns:
        row.append(latest_metric(conns[host['id']], default=0))
      else:
        row.append("?")
      rows.append(row)
  return rows

def assemble_info(domain):
  rows = []
  rows.append([
               ("KEY", curses.A_REVERSE),
               ("VALUE", curses.A_REVERSE)
               ])
  items =  args.__dict__
  for item in items:
    rows.append([(item.upper(), curses.A_BOLD), items[item]])
  rows.append([("REST URL", curses.A_BOLD), rest_url])
  rows.append([("UNIX TIME", curses.A_BOLD), str(int(time.time()))])
  rows.append([("ITERATION", curses.A_BOLD), str(iteration)])
  rows.append([("CONSOLE SIZE", curses.A_BOLD), "%d x %d" % size()])
  rows.append([("LAST RENDER TIME", curses.A_BOLD), str(int(render_time))])
  rows.append([("AVG RENDER TIME", curses.A_BOLD), str(int(sum(render_times)/len(render_times)))])
  return rows

def assemble_processes(domain):
  rows = []
  rows.append([
             ("DATABASE", curses.A_REVERSE),
             ("HOST", curses.A_REVERSE),
             ("REGION", curses.A_REVERSE),
             ("PORT", curses.A_REVERSE),
             ("TYPE", curses.A_REVERSE),
             ("PID", curses.A_REVERSE)
             ])
  try:
    databases = request(domain=domain, path="/databases")
    hosts = request(domain=domain, path="/hosts")
  except:
    rows.append(["ERROR", "FETCHING", "DATA"])
  else:
    for d_idx, database in enumerate(databases):
      for p_idx, process in enumerate(database['processes']):
        for host in hosts:
          if process['agentid'] == host['id']:
            databases[d_idx]['processes'][p_idx]['region'] = host['tags']['region']
    for database in databases:
      for process in sorted(sorted(sorted(database['processes'], key= lambda process: process['type']), key=lambda process: process['hostname']), key=lambda process: process['region']):
        row = []
        if process['status'] != "RUNNING":
          row.append((process['dbname'], curses.color_pair(3)))
        else:
          row.append((process['dbname'], curses.color_pair(1)))
        row.append(process['hostname'])
        row.append((process['region'], curses.A_BOLD))
        row.append(str(process['port']))
        row.append((str(process['type']), curses.A_BOLD))
        row.append(str(process['pid']))
        rows.append(row)
  return rows

def assemble_queries(domain):
  rows = []
  rows.append([
               ("QUERY", curses.A_REVERSE),
               ("TIME", curses.A_REVERSE),
               ("USER", curses.A_REVERSE),
               ("DATABASE", curses.A_REVERSE)
               ])
  active_queries = []
  databases = request(domain=domain, path="/databases")
  for database in databases:
    queries = request(domain=domain, path="/databases/%s/queries" % database['name'])
    for query in queries:
      if "statement" in query and 'statementHandle' in query and query['statementHandle'] >= 0:
        active_queries.append((query['time'], query['statement'], query['username'], database['name']))
  for query in sorted(active_queries, reverse=True):
    # we need to be conscious of query output width. therefore insert possible truncated query at end.
    line_len = 0
    row=[]
    for item in [query[0]/100, query[2], query[3]]:
      value = str(item)
      line_len += len(value) + 1
      row.append(value)
    statement = str(query[1])
    statement_width = width - line_len - 4
    if query[0] > 6000:
      attr = curses.color_pair(3)
    elif query[0] > 1000:
      attr = curses.color_pair(2)
    else:
      attr = curses.color_pair(1)
    row.insert(0, (statement[0:statement_width], attr))
    rows.append(row)
  return rows

def average_metric(data, length=4, red_threshold=90, yellow_threshold=75, format = None):
  acc = 0
  for measurement in data:
    acc += measurement['value']
  avg = acc / len(data)
  if avg > red_threshold:
    attr = curses.color_pair(3)
  elif avg > yellow_threshold:
    attr = curses.color_pair(2)
  else:
    attr = curses.color_pair(1)
  if format == "int":
    return (str(int(avg))[0:length], attr)
  else:
    return (str(avg)[0:length], attr)

def latest_metric(data, default = "?", length=4, red_threshold=90, yellow_threshold=75, format = None):
  timestamp = 0
  value = default
  for measurement in data:
    if measurement['timestamp'] > timestamp:
      value = measurement['value']
  if value > red_threshold:
    attr = curses.color_pair(3)
  elif value > yellow_threshold:
    attr = curses.color_pair(2)
  else:
    attr = curses.color_pair(1)
  if format == "int":
    return (str(int(value))[0:length], attr)
  else:
    return (str(value)[0:length], attr)

def request(domain, action="GET", path = "/", data= None, timeout=1 ):
  try:
    return domain.rest_req(action, path, data, timeout)
  except:
    return {}
  
def size():
  lines, cols = struct.unpack('hh',  fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, '1234'))
  return (lines,cols)

def malingerer(seconds=10):
  time.sleep(seconds)
  rows = []
  rows.append([
               ("Malingered for", curses.A_REVERSE),
               str(seconds), "seconds"
               ])
  return rows

def fork_thread(mode, domain):
  if mode == "info":
    t = ThreadWithReturnValue(target=assemble_info, args=(domain,))
  elif mode =="databases":
    t = ThreadWithReturnValue(target=assemble_databases, args = (domain,))
  elif mode == "processes":
    t = ThreadWithReturnValue(target=assemble_processes, args= (domain,))
  elif mode == "queries":
    t = ThreadWithReturnValue(target=assemble_queries, args=(domain,))
  else:
    t = ThreadWithReturnValue(target=assemble_hosts, args=(domain,))
  return t

class ThreadWithReturnValue(Thread):
  def __init__(self, group=None, target=None, name=None, args=(), kwargs={}, Verbose=None):
    Thread.__init__(self, group, target, name, args, kwargs, Verbose)
    self._return = None
  def run(self):
    if self._Thread__target is not None:
      self._return = self._Thread__target(*self._Thread__args, **self._Thread__kwargs)
  def join(self):
    Thread.join(self)
    return self._return

class Window:
  def __init__(self, height, width, starty, startx):
    self.object = curses.newwin(height, width, starty, startx)
    self.height = height
    self.line = 0
    self.col = 0
    self.width = width
  def clear(self):
    self.line = 0
    self.col = 0
    self.object.clear()
  def get(self):
    return self.object.getch()
  def move(self, starty, startx):
    self.clear()
    self.object.mvwin(starty, startx)
  def newline(self):
    self.line += 1
    self.col=0
  def refresh(self):
    self.object.refresh()
  def resize(self, height, width):
    self.height=height
    self.width=width
    self.object.resize(height, width)
  def write(self, string, attr = 0):
    if self.col + len(string) <= width:
      self.object.addstr(self.line, self.col, string, attr)
      self.col = self.col + len(string)
  def writeline(self, string, attr = 0):
    self.object.addstr(self.line, 0, string, attr)
    self.line += 1
  def write_block(self, data):
    self.clear()
    for line in data:
      if isinstance(line, (list, tuple)):
        if len(line) > 0:
          self.writeline(line[0], line[1])
        else:
          self.writeline(line[0])
      else:
        self.writeline(line)
  def write_table(self, data):
    self.clear()
    col_meta = {}
    for row in data:
      for idx, col in enumerate(row):
        if isinstance(col, (tuple, list)):
          val = str(col[0])
        else:
          val = str(col)
        if idx not in col_meta or len(val) > col_meta[idx]:
          col_meta[idx] = len(val)
    for row in data:
      for idx, col in enumerate(row):
        if isinstance(col, (tuple, list)):
          val = str(col[0])
          attr = col[1]
        else:
          val = str(col)
          attr = 0
        self.write(val, attr)
        if len(val) < col_meta[idx]:
          for i in range(0, col_meta[idx] - len(val)):
            self.write(" ")
        self.write(" ")
      self.newline()
       
parser = argparse.ArgumentParser(description=description)
parser.add_argument("-s", "--server", dest='host', action='store', help="server address running REST service", default="localhost")
parser.add_argument("-p", "--port", dest='port', action='store', help="server port running REST service", default=8888, type=int)
parser.add_argument("-u", "--user", dest='user', action='store', help="domain username", default="domain")
parser.add_argument("--password", dest='password', action='store', help="domain password", default="bird")
parser.add_argument("-i", "--compute-interval", dest='metric_interval', action='store', help="When computing metric data use data from the last N seconds", default=10, type=int)
parser.add_argument("-d", "--debug",  dest='debug', action='store_true')
args = parser.parse_args()
  
metric_interval = args.metric_interval # seconds
user=args.user
password=args.password
host=args.host
port=args.port
rest_url = "http://%s:%s/api" % (host, str(port))
iteration = 0 
data_thread = None
try:
  domain = nuodbTools.cluster.Domain(rest_url=rest_url, rest_username = user, rest_password = password)
  domain.rest_req(path="/databases")
except:
  print "ERROR: Unable to access REST service at %s:%s. Please check your configuration and try aagin." % ( host, port )
  exit (2)
windows = {}
try:
  curses.initscr()
  curses.start_color()
  curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
  curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
  curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
  curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLACK)
  curses.noecho()
  curses.halfdelay(10)
  i = 410
  oldmode=None
  mode="hosts"
  render_time = 0
  render_times = []
  while i != 101:
    mytime = int(time.time()) * 1000
    
    
    if i == 410:
      # redraw screen
      height, width = size()
      screen = curses.initscr()
      windows['header'] = Window(1, width,0,0)
      windows['footer'] = Window(1, width,height-1,0)
      windows['left'] = Window(height-2, int(width), 1,0)
      for window in windows:
        windows[window].clear()
        windows[window].refresh()
      windows['header'].writeline("nuotop - [h]osts [i]nfo [d]atabases [p]rocesses [q]ueries [e]xit")
    elif i == 113:
      mode = "queries"
    elif i == 104:
      mode = "hosts"
    elif i == 105:
      mode = "info"
    elif i == 100:
      mode = "databases"
    elif i == 112:
      mode = "processes"
    
    if oldmode != mode:
      windows['left'].clear()
      windows['left'].writeline("Loading...", curses.color_pair(4))
      windows['footer'].clear()
      data_thread = None
      rows = None
      if mode == "processes":
        windows['footer'].write("Processes in ")
        windows['footer'].write("RED", curses.color_pair(3))
        windows['footer'].write(" are in nonstandard state")
      elif mode == "hosts":
        windows['footer'].write("Hostnames in ")
        windows['footer'].write("GREEN", curses.color_pair(1))
        windows['footer'].write(" are brokers")
    
    for window in windows:
      windows[window].refresh()
    iteration += 1
    
    if data_thread == None:
      data_thread = fork_thread(mode, domain)
      data_thread.start()
      start_time = time.time()
    elif not data_thread.is_alive():
      rows = data_thread.join()
      data_thread = fork_thread(mode, domain)
      data_thread.start()
      start_time = time.time()

    if args.debug:
      windows['footer'].clear()
      elapsed_time = time.time() - start_time
      windows['footer'].writeline("data fetch time: %d mode: %s" % (elapsed_time, mode))
    end_time = time.time()
    if mode != "info":
      render_time = end_time - start_time
      render_times.append(int(render_time))
      
    if rows != None:
      windows['left'].clear()
      windows['left'].write_table(rows)
      windows['left'].refresh()
    i = screen.getch()
    oldmode=mode
  curses.endwin()
except KeyboardInterrupt:
  curses.endwin()
except:
  curses.endwin()
  e = sys.exc_info()
  print "".join(["ERROR: " + e[1].__str__() + "\n"] + traceback.format_tb(e[2]))
