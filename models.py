#!/usr/bin/env python
# encoding: utf-8
"""
models.py

Created by Maximillian Dornseif on 2010-09-05.
Copyright (c) 2010 HUDORA. All rights reserved.
"""


from google.appengine.dist import use_library
use_library('django', '1.1')


from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.api import xmpp
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp import util
import datetime
import django.utils.safestring
import hashlib
import logging
import os
import re
import urllib
import urlparse


# http://daringfireball.net/2010/07/improved_regex_for_matching_urls
url_re = re.compile(r'''(?i)\b((?:[a-z][\w-]+:(?:/{1,3}|[a-z0-9%])|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'".,<>?«»“”‘’]))''')
def linkreplace(matchobj):
    return '<a href="%s">%s</a>' % (urllib.quote(matchobj.group(0), "_.-/:@"), matchobj.group(0))


# Nutzer MIGHT map to a google user object
class Nutzer(db.Expando):
    handle = db.StringProperty(required=True)
    email = db.EmailProperty(required=False)
    user = db.UserProperty(required=False)
    avatar_url = db.LinkProperty(required=False)

    def get_url(self):
        return "/nutzer/%s" % self.handle

    def gravatar(self):
        if not self.email and self.avatar_url:
            return avatar_url
        gravhash = hashlib.md5(str(self.email)).hexdigest()
        query = urllib.urlencode({
            'gravatar_id': gravhash,
            's': 48,
            'default': 'http://zwitschr.hudora.biz/theme/default/default-avatar-profile.png',
            })
        return 'http://www.gravatar.com/avatar/?%s' % query



class Followed(db.Expando):
    nutzer = db.ReferenceProperty(Nutzer, collection_name='followed')
    followed_by = db.ReferenceProperty(Nutzer, collection_name='following')


class Zwitsch(db.Expando):
    guid =db.StringProperty(required=False)
    content = db.StringProperty(required=True)
    created_at = birthdate = db.DateTimeProperty(auto_now_add=True)
    handle = db.StringProperty(required=True)
    user = db.UserProperty(required=False, auto_current_user_add=True)
    nutzer = db.ReferenceProperty(Nutzer, collection_name='zwitsches')
    email = db.EmailProperty(required=False)
    source = db.StringProperty(required=False, default='web')
    in_reply_to = db.StringProperty(required=False)

    def __unicode__(self):
        context = {'handle': self.handle,
                   'gravatar': self.gravatar(),
                   'content': self.content_as_html(),
                   'link': self.get_url(),
                   'timestamp': self.created_at}
        return django.utils.safestring.mark_safe("""<div class="zwitsch">
          <span class="vcard author"><a href="/nutzer/%(handle)s"><img src="%(gravatar)s" class="avatar photo" width="48" height="48"></a> <a href="/nutzer/%(handle)s">%(handle)s</a></span>
          <p>%(content)s</p>
          <a rel="bookmark" class="timestamp" href="%(link)s"><abbr class="published" title="%(timestamp)s">%(timestamp)s</abbr></a>
        </div>""" % context)
    
    def __cmp__(self, other):
        return cmp((self.created_at, other), (self.created_at, other))

    def get_url(self):
        return "/zwitsch/%s" % self.guid

    def gravatar(self):
        gravhash = hashlib.md5(str(self.email)).hexdigest()
        query = urllib.urlencode({
            'gravatar_id': gravhash,
            's': 48,
            'default': 'http://zwitschr.hudora.biz/theme/default/default-avatar-profile.png',
            })
        return 'http://www.gravatar.com/avatar/?%s' % query

    def content_as_html(self):
        return url_re.sub(linkreplace, self.content)
        
    def get_parents(self):
        logging.info(self.in_reply_to)
        ret = []
        if self.in_reply_to:
            results = Zwitsch.all().filter('guid =', self.in_reply_to)
            if results.count() > 0:
                ret.append(results[0])
                parentresults = results[0].get_parents()
                if parentresults:
                    ret.append(parentresults)
        return ret


def create_zwitch(content, user=None, email=None, handle=None, guid=None, in_reply_to=None, created_at=None):
    if Zwitsch.get_by_key_name(guid):
        raise ValueError("Duplicate GUID %s" % guid)
    content = content.replace('\n', ' ').replace('\r', ' ')
    if (not email) and user and user.email():
        email = user.email()
    if (not handle) and email:
        handle = email_to_handle(email)

    nutzerresults = Nutzer.all().filter('handle =', handle)
    if nutzerresults.count() < 1:
        # Wir müssen den models.Nutzer neu anlegen
        nutzer = Nutzer(email=email, handle=handle)
        nutzer.put()
    else:
        nutzer = nutzerresults[0]
    zwitsch = Zwitsch(key_name=guid, guid=guid, content=content, handle=handle, in_reply_to=in_reply_to, nutzer=nutzer)
    if user:
        zwitsch.user = user
    if email:
        zwitsch.email = email
    if created_at:
        zwitsch.created_at = created_at
    zwitsch.put()
    return zwitsch


def email_to_handle(email):
    handle = email.split('@')[0]
    return handle.replace('.', '')
