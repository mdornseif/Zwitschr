#!/usr/bin/env python
# encoding: utf-8
"""
formats.py

Created by Maximillian Dornseif on 2010-09-05.
Copyright (c) 2010 HUDORA. All rights reserved.
"""

import xml.etree.cElementTree as ET
import functools
import datetime

# from http://svn.python.org/projects/peps/trunk/PyRSS2Gen.py
def _format_date(dt):
    """convert a datetime into an RFC 822 formatted date

    Input date must be in GMT.
    """
    # Looks like:
    #   Sat, 07 Sep 2002 00:00:01 GMT
    # Can't use strftime because that's locale dependent
    #
    # Isn't there a standard way to do this for Python?  The
    # rfc822 and email.Utils modules assume a timestamp. The
    # following is based on the rfc822 module.
    return "%s, %02d %s %04d %02d:%02d:%02d GMT" % (
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dt.weekday()],
            dt.day,
            ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][dt.month-1],
            dt.year, dt.hour, dt.minute, dt.second)

# from myPLfrontend/experiment.py
def _ConvertDictToXmlRecurse(parent, dictitem, listnames):
    # we can't convert bare lists
    assert not isinstance(dictitem, list)

    if isinstance(dictitem, dict):
        for (tag, child) in dictitem.iteritems():
            if isinstance(child, list):
                # iterate through the array and convert
                listelem = ET.Element(tag)
                parent.append(listelem)
                for listchild in child:
                    elem = ET.Element(listnames.get(tag, 'item'))
                    listelem.append(elem)
                    _ConvertDictToXmlRecurse(elem, listchild, listnames)
            else:
                elem = ET.Element(tag)
                parent.append(elem)
                _ConvertDictToXmlRecurse(elem, child, listnames)
    else:
        parent.text = unicode(dictitem)
    

def ConvertDictToXml(xmldict, roottag='data', listnames=None):
    """
    Converts a dictionary to an XML ElementTree Element::
    
    >>> data = {"nr": "xq12", "positionen": [{"menge": 12}, {"menge": 2}]}
    >>> root = ConvertDictToXml(data)
    >>> ET.tostring(root)
    <data><nr>xq12</nr><positionen><item><menge>12</menge></item><item><menge>2</menge></item></positionen></data>
    
    Per default ecerything ins put in an enclosing '<data>' element. Also per default lists are converted
    to collecitons of `<item>` elements. But by provding a mapping between list names and element names,
    you van generate different elements::
    
    >>> data = {"positionen": [{"m": 12}, {"m": 2}]}
    >>> root = ConvertDictToXml(data, roottag='xml)
    >>> ET.tostring(root)
    <xml><positionen><item><m>12</m></item><item><m>2</m></item></positionen></xml>

    >>> root = ConvertDictToXml(data, roottag='xml, listnames={'positionen': 'position'})
    >>> ET.tostring(root)
    <xml><positionen><position><m>12</m></position><position><m>2</m></position></positionen></xml>
    """
    
    if not listnames:
        listnames = {}
    root = ET.Element(roottag)
    _ConvertDictToXmlRecurse(root, xmldict, listnames)
    return root

def ConvertListToXML(xmllist, root, elementname):
    basexml = ConvertDictToXml({root: xmllist}, 'xml', listnames={root: elementname})
    return basexml.find(root)


# from http://effbot.org/zone/element-builder.htm
class _E(object):
    def __call__(self, tag, *children, **attrib):
        elem = ET.Element(tag, attrib)
        for item in children:
            if isinstance(item, dict):
                elem.attrib.update(item)
            elif ET.iselement(item):
                elem.append(item)
            elif isinstance(item, basestring):
                if len(elem):
                    elem[-1].tail = (elem[-1].tail or "") + item
                else:
                    elem.text = (elem.text or "") + item
            else:
                raise TypeError("bad argument: %r" % item)
        return elem

    def __getattr__(self, tag):
        return functools.partial(self, tag)

# create factory object
E = _E()

def _dummy_urlfixer(url):
    return url

def rss_build_entry(zwitsch, urlfixer):
    entry = E.entry(
             E.author(E.name(zwitsch.handle)),
             E.title(zwitsch.content),
             E.content(zwitsch.content_as_html(), type="html"),
             E.published(zwitsch.created_at.isoformat()),
             E.updated(zwitsch.created_at.isoformat()),
             E.link(type="text/html", rel="alternate", href=urlfixer(zwitsch.get_url())),
             E('twitter:source', zwitsch.source),
             E.id('tag:hudora.de,2010:%s' % zwitsch.get_url()),
    )
    return entry


def rss_build_timeline(nutzer, urlfixer):
    entries = []
    last_modified = datetime.datetime(1973, 8, 8)
    for zwitsch in nutzer.zwitsches.order('-created_at').fetch(30):
        entries.append(rss_build_entry(zwitsch, urlfixer))
        last_modified = max([last_modified, zwitsch.created_at])
    
    kwargs = {'xmlns': "http://www.w3.org/2005/Atom",
              'xmlns:twitter': "http://api.twitter.com"}
    args = [E.title('Twitter / themattharris with friends'),
      E.subtitle('Twitter updates and retweets from Matt Harris / themattharris and folks.'),
      E.id('tag:hudora.de,2010:Status'),
      E.updated(last_modified.isoformat()),
      E.link(type="text/html", rel="alternate", href=urlfixer(nutzer.get_url())),
      # E.link(type="application/atom+xml", rel="self", href="https://api.twitter.com/1/statuses/home_timeline.atom?count=30")
      ] + entries
    tree =E.feed(*args, **kwargs)
    return tree


    in_reply_to = db.StringProperty(required=False)

def build_entry(zwitsch):
    return dict(
    id=zwitsch.guid,
    created_at=_format_date(zwitsch.created_at),
    text=zwitsch.content,
    source=zwitsch.source,
    in_reply_to_status_id='',
    in_reply_to_user_id='',
    in_reply_to_screen_name='',
    favorited=False,
    truncated=False,
    geo='',
    coordinates='',
    place='',
    contributors='',
    annotations='',
    entities=dict(urls='', user_mentions='', hashtags=''),
    user=dict(created_at='2010-01-01',
        id=zwitsch.handle,
        name=zwitsch.handle,
        screen_name=zwitsch.handle,
        profile_image_url=zwitsch.gravatar(),
        followers_count=1,
        friends_count=2,
        statuses_count=3,
        favourites_count=4,
        notifications=False,
        following=False,
        location='',
        description='',
        url='',
        protected='',
        utc_offset=7200,
        time_zone='Central European Time',
        geo_enabled=False,
        verified=False,
        lang='de',
        contributors_enabled=False,
        follow_request_sent=False,
        profile_background_image_url='',
        profile_background_tile=False,
        profile_use_background_image=False,
        profile_background_color='FFFFFF',
        profile_text_color='000000',
        profile_link_color='0000FF',
        profile_sidebar_fill_color='AD0066',
        profile_sidebar_border_color='AD0066',
        ),
    )


def build_timeline(nutzer):
    entries = []
    for zwitsch in nutzer.timeline():
        entries.append(build_entry(zwitsch))
    return entries


def timeline_as_rss(nutzer, urlfixer=None):
    if not urlfixer:
        urlfixer = _dummy_urlfixer
    tree = rss_build_timeline(nutzer, urlfixer)
    return ET.tostring(tree)


def timeline_as_xml(nutzer, urlfixer=None):
    """Return timeline ("friends feed") for an user in Twitter compatible XML format."""
    return ET.tostring(ConvertListToXML(build_timeline(nutzer), 'statuses', 'status'))


def timeline_as_json(nutzer, urlfixer=None):
    return json.dumps(build_timeline(nutzer))


def zwitsch_as_xml(zwitsch):
    return ET.tostring(ConvertDictToXml(build_entry(zwitsch), 'status'))
