#!/usr/bin/env python
# encoding: utf-8

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
import formats
import functools
import hashlib
import logging
import models
import os
import re
import urllib
import urlparse


def http_basic_auth(method):
    "Prefix user to method call. Authenticates using HTTP Basic Authorization."
    @functools.wraps(method)
    def http_basic_auth_deco(self, *args):
        basic_auth = self.request.headers.get('Authorization')
        if not basic_auth:
            self.error(401)
            self.response.headers['Content-Type'] = 'application/xml; charset=utf-8'
            self.response.headers['WWW-Authenticate'] = 'Basic realm="Zwitscher API"'
            self.response.out.write('<hash>request>/statuses/replies.xml</request>error>Could not authenticate you.</error></hash>')
            return
        username, password = '', ''
        user_info = basic_auth[6:].decode('base64')
        username, password = user_info.split(':')
        nutzer = models.Nutzer.all().filter('handle =', username).filter('api_key =', password).get()
        if not nutzer:
            logging.info('wrong credentials %s:%s - ' % (username, password))
            # if generate api_key if needed
            nutzer = models.Nutzer.all().filter('handle =', username).get()
            if nutzer:
                logging.info(nutzer.get_api_key())
            self.error(403)
            self.response.headers['Content-Type'] = 'application/xml; charset=utf-8'
            self.response.headers['WWW-Authenticate'] = 'Basic realm="Zwitscher API"'
            self.response.out.write('<?xml version="1.0" encoding="UTF-8"?><errors><error code="32">Could not authenticate you</error></errors>')
            return
        else:
            return method(self, nutzer, *args)
    return http_basic_auth_deco


class ZwitscherRequestHandler(webapp.RequestHandler):
    def _create_absolute_url(self, url):
        scheme, host, path, query, fragment = urlparse.urlsplit(self.request.url)
        return urlparse.urljoin('%s://%s' % (scheme, host), url)

    def get_aktueller_nutzer(self):
        # force Login
        user = users.get_current_user()
        logging.debug(user)
        if not user:
            self.redirect(self.create_openid_url(self.request.url))
            return None

        results = models.Nutzer.all().filter('user =', user)
        if results.count() < 1:
            aktueller_nutzer = models.Nutzer(email=user.email(), user=user,
                                             handle=models.email_to_handle(user.email()))
        else:
            aktueller_nutzer = results[0]
        
        aktueller_nutzer.put()
        aktueller_nutzer.logout_url = users.create_logout_url('/')
        aktueller_nutzer.is_admin = users.is_current_user_admin()
        return aktueller_nutzer

    def create_openid_url(self, continue_url):
        continue_url = urlparse.urljoin(self.request.url, continue_url)
        return "/_ah/login_required?continue=%s" % urllib.quote(continue_url)


class TimelineHandler(ZwitscherRequestHandler):
    def get(self):
        aktueller_nutzer = self.get_aktueller_nutzer()
        template_values = {
            'zwitsches': aktueller_nutzer.timeline(),
            'aktueller_nutzer': aktueller_nutzer,
            }
        path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
        self.response.out.write(template.render(path, template_values))


class MainHandler(ZwitscherRequestHandler):
    def get(self):
        aktueller_nutzer = self.get_aktueller_nutzer()
        if not aktueller_nutzer:
            return
        zwitsches = models.Zwitsch.all().order('-created_at').fetch(30)
        template_values = {
            'zwitsches': zwitsches,
            'aktueller_nutzer': aktueller_nutzer,
            }
        path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
        self.response.out.write(template.render(path, template_values))

    def post(self):
        user = users.get_current_user()
        if user:
            aktueller_nutzer = models.Nutzer.all().filter('user =', user).get()

        args = dict(content=self.request.get('content'))
        if self.request.get('created_at'):
            # timezonehandling needs more thought
            ts = self.request.get('created_at')
            if '+' in ts:
                ts, tz = ts.split('+')
                tz_h, tz_m = tz.split(':')
                created_at = datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S')
                created_at = created_at - datetime.timedelta(hours=int(tz_h), minutes=int(tz_m))
            else:
                created_at = datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S')
            args['created_at'] = created_at
        if self.request.get('in_reply_to'):
            args['in_reply_to'] = self.request.get('in_reply_to')
        if self.request.get('guid'):
            args['guid'] = self.request.get('guid')
        if self.request.get('email'):
            args['email'] = self.request.get('email')
        if self.request.get('handle'):
            args['handle'] = self.request.get('handle')
        if not args.get('handle'):
             args['handle'] = aktueller_nutzer.handle

        # prevent dupes
        if self.request.get('guid'):
            if models.Zwitsch.get_by_key_name(self.request.get('guid')):
                self.error(409)
                self.response.out.write("Duplicate GUID %s" % self.request.get('guid'))
                return
        zwitsch = models.create_zwitch(**args)
        self.redirect(zwitsch.get_url())


class ZwitschHandler(ZwitscherRequestHandler):
    def get(self, zwitschkey):
        aktueller_nutzer = self.get_aktueller_nutzer()

        if not zwitschkey:
            self.redirect('..')
        else:
            results = models.Zwitsch.all().filter('guid =', zwitschkey)
            if results.count() < 1:
                self.error(404)
                return
            zwitsch = results[0]
            template_values = {
                'zwitsch': zwitsch,
                'aktueller_nutzer': aktueller_nutzer,
                }
            path = os.path.join(os.path.dirname(__file__), 'templates/zwitsch.html')
            self.response.out.write(template.render(path, template_values))


class UserHandler(ZwitscherRequestHandler):
    def get(self, handle):
        aktueller_nutzer = self.get_aktueller_nutzer()

        if not handle:
            self.redirect('..')
        else:
            zwitsches = models.Zwitsch.all().filter('handle =', handle).order('-created_at').fetch(30)
            nutzerresults = models.Nutzer.all().filter('handle =', handle)
            if nutzerresults.count() < 1:
                # Wir müssen den models.Nutzer neu anlegen
                email = None
                for zwitsch in zwitsches:
                    if zwitsch.email:
                        email = zwitsch.email
                        break
                if zwitsches.count < 1:
                    # REALLY a unknown user
                    self.error(404)
                    return
                nutzer = models.Nutzer(email=email, handle=handle)
                nutzer.put()
            else:
                nutzer = nutzerresults[0]

            template_values = {
                'zwitsches': zwitsches,
                'aktueller_nutzer': aktueller_nutzer,
                'nutzer': nutzer
                }
            path = os.path.join(os.path.dirname(__file__), 'templates/nutzer.html')
            self.response.out.write(template.render(path, template_values))


class UserSettingsHandler(ZwitscherRequestHandler):
    def get(self, handle):
        nutzer = self.get_aktueller_nutzer()

        if not handle:
            self.redirect('/')
        else:
            template_values = {
                'aktueller_nutzer': nutzer,
                'nutzer': nutzer
                }
            path = os.path.join(os.path.dirname(__file__), 'templates/settings.html')
            self.response.out.write(template.render(path, template_values))


class UserFollowHandler(ZwitscherRequestHandler):
    def get(self, handle):
        aktueller_nutzer = self.get_aktueller_nutzer()
        if not handle:
            self.redirect('..')
        else:
            nutzerresults = models.Nutzer.all().filter('handle =', handle)
            if nutzerresults.count() < 1:
                # Wir müssen den models.Nutzer neu anlegen
                email = None
                for zwitsch in zwitsches:
                    if zwitsch.email:
                        email = zwitsch.email
                nutzer = models.Nutzer(email=email, handle=handle)
                nutzer.put()
            else:
                nutzer = nutzerresults[0]
            
            # aktueller_nutzer wants to follow nutzer
            followship = models.Followed.all().filter('nutzer =', nutzer
                                                      ).filter('followed_by =', aktueller_nutzer).get()
            if not followship:
                models.Followed(nutzer=nutzer, followed_by=aktueller_nutzer).put()
            else:
                followship.delete()
            self.response.out.write("OK")


class ApiUpdate(ZwitscherRequestHandler):
    @http_basic_auth
    def post(self, nutzer):
        args = dict(handle=nutzer.handle, content=self.request.get('status'), source=self.request.get('source'))
        if self.request.get('in_reply_to_status_id'):
            args['in_reply_to'] = self.request.get('in_reply_to_status_id')
        zwitsch = models.create_zwitch(**args)
        self.response.headers['Content-Type'] = 'application/xml; charset=utf-8'
        self.response.out.write(formats.zwitsch_as_xml(zwitsch))


class ApiTimeline(ZwitscherRequestHandler):
    @http_basic_auth
    def get(self, nutzer):
        self.response.headers['Content-Type'] = 'application/xml; charset=utf-8'
        self.response.out.write(formats.timeline_as_xml(nutzer, self._create_absolute_url))


class ApiTimelineRSS(ZwitscherRequestHandler):
    @http_basic_auth
    def get(self, nutzer):
        self.response.headers['Content-Type'] = 'application/xml; charset=utf-8'
        self.response.out.write(formats.timeline_as_rss(nutzer, self._create_absolute_url))


class ApiRateLimit(ZwitscherRequestHandler):
    """This is a dummy."""
    @http_basic_auth
    def get(self, nutzer):
        self.response.headers['Content-Type'] = 'application/xml; charset=utf-8'
        self.response.out.write("""<?xml version="1.0" encoding="UTF-8"?>
<hash>
    <remaining-hits type="integer">20000</remaining-hits>
    <hourly-limit type="integer">20000</hourly-limit>
    <reset-time type="datetime">%s</reset-time>
    <reset-time-in-seconds type="integer">1</reset-time-in-seconds>
</hash>""" % datetime.datetime.now().isoformat())


class ApiReplies(ZwitscherRequestHandler):
    """This is a dummy."""
    @http_basic_auth
    def get(self, nutzer):
        self.response.headers['Content-Type'] = 'application/xml; charset=utf-8'
        self.response.out.write("""<?xml version="1.0" encoding="UTF-8"?>
<statuses type="array">
</statuses>""")


class XMPPHandler(ZwitscherRequestHandler):
    """Eingehende Nachricht per XMPP/Jabber.
       
       Muss an /_ah/xmpp/message/chat/ gebunden sein."""
        
    def post(self):
        message = xmpp.Message(self.request.POST)
        sender = message.sender.split('/')[0]
        zwitsch = models.create_zwitch(message.body, email=sender)
        message.reply("See %s" % self._create_absolute_url(zwitsch.get_url()))
        self.response.out.write('OK')


################

from google.appengine.api.users import get_current_user, create_login_url


class OpenIdLoginHandler(webapp.RequestHandler):
  def get(self):
    continue_url = self.request.GET.get('continue')
    openid_url = None
    if self.request.GET.get('cyberlogi.x'):
        openid_url = 'https://www.google.com/accounts/o8/site-xrds?hd=cyberlogi.de'
    if self.request.GET.get('hudora.x'):
        openid_url = 'https://www.google.com/accounts/o8/site-xrds?hd=hudora.de'
    logging.info(openid_url)
    if not openid_url:
      path = os.path.join(os.path.dirname(__file__), 'templates', 'login.html')
      self.response.out.write(template.render(path, {'continue': continue_url}))
    else:
      self.redirect(users.create_login_url(continue_url, None, openid_url))



def main():
    application = webapp.WSGIApplication([
        ('/_ah/login_required', OpenIdLoginHandler),
        # API
        ('/statuses/friends_timeline.rss', ApiTimelineRSS),
        ('/statuses/friends_timeline.xml', ApiTimeline),
        ('/statuses/update.xml', ApiUpdate),
        ('/statuses/replies.xml', ApiReplies),
        ('/statuses/mentions.xml', ApiReplies),
        ('/account/rate_limit_status.xml', ApiRateLimit),
        ('/_ah/xmpp/message/chat/', XMPPHandler),
        # User facing
        ('/zwitsch/(.+)', ZwitschHandler),
        ('/nutzer/([a-z]+)/change_follow_status', UserFollowHandler),
        ('/nutzer/([a-z]+)/settings', UserSettingsHandler),
        ('/nutzer/([a-z]+)', UserHandler),
        ('/timeline', TimelineHandler),  # Subscribte Tweets
        ('/', MainHandler),              # Alle Tweets
        ], debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
