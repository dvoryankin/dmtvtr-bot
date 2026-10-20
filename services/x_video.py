"""Public X video download; no credentials or alternative fetchers."""
import re
from urllib.parse import urlsplit

HOSTS = {'x.com','www.x.com','mobile.x.com','twitter.com','www.twitter.com','mobile.twitter.com'}
URL_RE = re.compile(r'https?://[^\s<>]+')

def canonical_url(value):
 try:
  p=urlsplit(value)
  if p.scheme != 'https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None,443):return None
  if not re.fullmatch(r'/[A-Za-z0-9_]{1,50}/status/[0-9]{1,25}/?',p.path):return None
  return 'https://x.com'+p.path.rstrip('/')
 except (ValueError,TypeError):return None

import asyncio
import json
import socket
import tempfile
from pathlib import Path
from collections import namedtuple
import aiohttp
from services.instagram_network import public_ip
from services.instagram_video_metadata import probe_video_dimensions

MAX_FILE=45*1024*1024
MAX_TOTAL=90*1024*1024
Item=namedtuple('Item','value width height')

def validate_fetch_url(url):
 p=urlsplit(url)
 if (p.scheme!='https' or p.hostname not in {'api.fxtwitter.com','video.twimg.com'}
     or p.username or p.password or p.port not in (None,443) or p.fragment):raise ValueError('network_guard')
 if p.hostname=='api.fxtwitter.com' and not re.fullmatch(r'/status/[0-9]{1,25}',p.path):raise ValueError('network_guard')
 return url

class GuardResolver(aiohttp.abc.AbstractResolver):
 async def resolve(self,host,port=443,family=socket.AF_INET):
  validate_fetch_url('https://'+host+('/status/1' if host=='api.fxtwitter.com' else '/'))
  if port!=443:raise ValueError('network_guard')
  rows=await asyncio.get_running_loop().run_in_executor(None,lambda:socket.getaddrinfo(host,port,family,socket.SOCK_STREAM))
  if not rows or any(not public_ip(row[4][0]) for row in rows):raise ValueError('network_guard')
  return [dict(hostname=host,host=row[4][0],port=443,family=row[0],proto=row[2],flags=socket.AI_NUMERICHOST) for row in rows]
 async def close(self):pass

async def bounded_read(content,limit,path=None):
 size=0;chunks=[]
 stream=path.open('wb') if path else None
 try:
  async for chunk in content.iter_chunked(65536):
   size+=len(chunk)
   if size>limit:raise ValueError('too_large')
   if stream:stream.write(chunk)
   else:chunks.append(chunk)
 finally:
  if stream:stream.close()
 return size if path else b''.join(chunks)

async def fetch(session,url,path=None,limit=None,method='GET'):
 validate_fetch_url(url)
 limit=limit if limit is not None else 1024*1024
 async with session.request(method,url,allow_redirects=False) as response:
  if response.status!=200:raise ValueError('http_error')
  if method=='HEAD':return response.content_length
  if response.content_length is not None and response.content_length>limit:raise ValueError('too_large')
  result=await bounded_read(response.content,limit,path)
  return result if path else json.loads(result)

class XService:
 def __init__(self,allowed_chats):
  self.allowed_chats=set(allowed_chats);self.pending=0;self.chats={};self.locks={};self.active=None;self.seen={}
 async def handle(self,chat,url,send,message_id=None):
  url=canonical_url(url)
  if chat not in self.allowed_chats or not url:raise ValueError('scope')
  key=(chat,message_id,url)
  # Bounded process-local incoming-message receipts, including ambiguous sends.
  if key in self.seen:return False
  if self.pending>=20 or self.chats.get(chat,0)>=10:raise ValueError('busy')
  self.seen[key]=True
  if len(self.seen)>2048:self.seen.pop(next(iter(self.seen)))
  self.pending+=1;self.chats[chat]=self.chats.get(chat,0)+1
  if self.active is None:self.active=asyncio.Semaphore(2)
  lock=self.locks.setdefault(chat,asyncio.Lock())
  async def work():
   async with lock:
    async with self.active:
     async def download_send():
      with tempfile.TemporaryDirectory(prefix='x-video-') as tmp:
       connector=aiohttp.TCPConnector(resolver=GuardResolver(),use_dns_cache=False)
       async with aiohttp.ClientSession(connector=connector,trust_env=False,cookie_jar=aiohttp.DummyCookieJar(),timeout=aiohttp.ClientTimeout(total=90)) as session:
        data=await fetch(session,'https://api.fxtwitter.com/status/'+url.rsplit('/',1)[1])
        media=data.get('tweet',{}).get('media',{})
        if any(x.get('type') not in ('video','gif') for x in media.get('all',[])):raise ValueError('unsupported_media')
        videos=media.get('videos') or [x for x in media.get('all',[]) if x.get('type') in ('video','gif')]
        if not 1<=len(videos)<=10:raise ValueError('no_video')
        items=[];total=0
        for index,video in enumerate(videos):
         candidates=[video]+[v for name in ('formats','variants') for v in (video.get(name) or []) if isinstance(v,dict)]
         candidates=[v for v in candidates if isinstance(v.get('url'),str) and urlsplit(v['url']).path.endswith('.mp4')]
         candidates.sort(key=lambda v:float(v.get('bitrate') or 0),reverse=True)
         chosen=None
         for candidate in candidates:
          address=validate_fetch_url(candidate['url'])
          if urlsplit(address).hostname!='video.twimg.com':raise ValueError('network_guard')
          size=await fetch(session,address,limit=MAX_FILE,method='HEAD')
          if isinstance(size,int) and size>MAX_FILE:continue
          chosen=address;break
         if chosen is None:raise ValueError('no_video')
         path=Path(tmp)/('%s.mp4'%index)
         total+=await fetch(session,chosen,path=path,limit=min(MAX_FILE,MAX_TOTAL-total))
         with path.open('rb') as stream:header=stream.read(32)
         if b'ftyp' not in header:raise ValueError('invalid_file')
         dims=await probe_video_dimensions(path)
         if not dims:raise ValueError('invalid_file')
         items.append(Item(path,*dims))
        return bool(await send(items))
     return await asyncio.wait_for(download_send(),90)
  try:return await asyncio.wait_for(work(),990)
  finally:
   self.pending-=1;self.chats[chat]-=1
   if not self.chats[chat]:
    self.chats.pop(chat);self.locks.pop(chat,None)
