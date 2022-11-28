#!/usr/bin/env python
# coding=utf-8

#
# Copyright 2014 Meetin.gs Ltd.
#

import os
import json
import urllib
import math
import datetime

import webapp2
import jinja2

from google.appengine.ext import ndb
from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers

import sys
sys.path.append('vendor')

import httplib2

import logging

JINJA_ENVIRONMENT = jinja2.Environment( loader=jinja2.FileSystemLoader(os.path.dirname(__file__) + '/template' ), extensions=['jinja2.ext.autoescape'] )

cuty_secret = 'somewhatsecret9211'
startingminweight = 8
startingmaxweight = 64

futusome_url_base = 'https://api.futusome.com/api/terms.json'
futusome_query_defaults = {
    'api_key' : 'fd85ed64a2f5d11694be295c1e7cf3b2',

    'api_term[group]' : 'text.substantive',
    'api_term[sort]' : 'absoluteFrequency',
    'api_term[min_term_length]' : '3',
    'api_term[min_rel_freq]' : '0.0',
    'api_term[min_abs_freq]' : '0',

    'api_term[n]' : '50',
    'api_term[min_lift]' : '5',

    'api_term[context]' : '',
    'api_term[query]' : '',
}

config = {
    'example' : {
        'auth' : 'sala9000',
        'futusome_rolling_days' : 30,
        'futusome_query_override' : {
            'api_key' : '502016dc63990a404838c08fce37d14e',
            'api_term[query]' : '((text.base:example AND text.base:(netti OR asiakaspalvelu OR välittäjäpalvelu OR kontaktienohjaus OR videoavusteinen OR konesali OR luuri OR mobiili OR data OR valokuitu OR kiinteistökuitu OR lumia OR android OR samsung OR apple OR nokia OR iphone OR lte OR verkko OR operaattori OR liittymä OR gsm OR 3g OR laajakaista OR nettiyhteys OR kännykkä OR puhelin OR aspa OR puhelu OR 4g OR nopeus OR taloyhtiö OR tablet* OR ipad OR digiboksi OR taulutietokone OR roaming* OR taajuus OR kaapeli OR antenni OR palvelin OR reititin OR kuuluvuus OR hinta OR kanavapaketti)) OR (text.base:"example viihde"~3 OR text.base:"example kirja"~3 OR text.base:"example puhe"~3 OR text.base:"example lompakko"~3 OR text.base:"example vahti"~3 OR text.base:"example idea"~3 OR text.naive:orangecontact*) OR (page-title.base:"example viihde"~3 OR page-title.base:"example kirja"~3 OR page-title.base:"example puhe"~3 OR page-title.base:"example lompakko"~3 OR page-title.base:"example vahti"~3 OR page-title.base:"example idea"~3 OR page-title.naive:orangecontact*)) AND (text.length:[20 TO 3000] OR type:blog*) AND NOT text.base:saunalahti',
        },
        'width' : 450,
        'height' : 365,
        'background_color' : '#283845',
    }
}

def current_config(self):
    client = self.request.get('client')
    if client in config:
        return config[client]
    return False

def form_futusome_update_url( self ):
    c = current_config(self)

    query = futusome_query_defaults.copy();
    if 'futusome_query_override' in c:
        for key in c['futusome_query_override']:
            query[key] = c['futusome_query_override'][key]

    if 'futusome_rolling_days' in c and c['futusome_rolling_days'] > 0:
        today = datetime.datetime.now()
        today_stamp = today.strftime('%Y%m%d')

        month_ago = today - datetime.timedelta( days = c['futusome_rolling_days'] )
        month_ago_stamp = month_ago.strftime('%Y%m%d')

        clause = 'published.day:[' + month_ago_stamp + ' TO ' + today_stamp + ']'

        query['api_term[context]'] = ''
        query['api_term[query]'] = clause + ' AND (' + query['api_term[query]'] + ')'
    else:
        query['api_term[context]'] = ''

    return futusome_url_base + '?' + urllib.urlencode( query )


def update_futusome_data( self ):
    futusome_url = form_futusome_update_url( self )
    http = httplib2.Http( timeout = 60 )
    resp, content = http.request( futusome_url )
    if str( resp['status'] ) == '200':
        try:
            data = json.loads( content )
        except:
            logging.error("Error parsing this as JSON: " + content )
        if 'terms' in data:
            GlobalData.store('latest_data_' + self.request.get('client'), content )

def has_wrong_auth(self):
    c = current_config(self)
    auth = self.request.get('auth')
    if c == False:
        self.error(404)
        return True
    if auth == '':
        self.error(403)
        return True
    if auth != c['auth']:
        self.error(403)
        return True

    return False

def state_url_query( self ):
    client = self.request.get('client')
    auth = self.request.get('auth')

    return urllib.urlencode( { "client" : client, "auth" : auth } );

class RenderAwesomeHandler(webapp2.RequestHandler):
    def get(self):
        if has_wrong_auth(self):
            return

        c = current_config(self)

        json_data = GlobalData.fetch('latest_data_' + self.request.get('client'))
        data = json.loads( json_data )

        terms = []
        for term_dict in data['terms']:
            terms.append( { "term" : term_dict['term'], "absweight" : term_dict['absoluteFrequency'] } );

        terms.sort(key=lambda x: x["absweight"])

        weights = { "high" : 0, "low" : 99999, "cumulative" : 0, "count" : 0, "mid" : 0 };
        for term in terms:
            if term['absweight'] > weights['high']:
                weights['high'] = term['absweight']
            if term['absweight'] < weights['low']:
                weights['low'] = term['absweight']


            weights['cumulative'] = weights['cumulative'] + term['absweight']
            weights['count'] = weights['count'] + 1
            if weights['mid'] == 0 and weights['count'] > len( terms ) / 2:
                weights['mid'] = term['absweight']


        weights["range"] = weights["high"] - weights["low"]
        weights["avgrange"] = weights["low"] + math.floor( weights["range"] / 2 )
        weights["avgweight"] = math.floor( weights['cumulative'] / weights['count'] )

        minweight = startingminweight
        maxweight = startingmaxweight - ( math.floor( len( terms ) / 12 ) * 8 )
        if maxweight < minweight * 2:
            maxweight = minweight * 2
        midweight = math.floor( ( minweight + maxweight ) / 2 )

        for term in terms:
            if term["absweight"] < weights['mid']:
                if weights["mid"] > weights["low"]:
                    term["weight"] = midweight - math.floor( ( midweight - minweight ) * ( term["absweight"] -  weights["low"] ) / ( weights["mid"] -  weights["low"] ) )
                else:
                    term["weight"] = midweight

            else:
                if weights["high"] > weights["mid"]:
                    term["weight"] = midweight + math.ceil( ( maxweight - midweight ) * ( term["absweight"] -  weights["mid"] ) / (  weights["high"] -  weights["mid"] ) )
                else:
                    term["weight"] = midweight

        template_values = {
            "terms" : terms,
            "background_color" : c["background_color"]
        }
        template = JINJA_ENVIRONMENT.get_template('awesome.jinja2')
        self.response.write(template.render(template_values))

class UpdateHandler(webapp2.RequestHandler):
    def get(self):
        if has_wrong_auth(self):
            return

        c = current_config(self)

        update_futusome_data( self )

        render_url = 'https://' + os.environ['HTTP_HOST'] + '/renderawesome?' +  state_url_query(self)

        receive_url_abs = '/receive?' + state_url_query(self)
        upload_url = blobstore.create_upload_url( receive_url_abs )

        cuty_url = 'https://cuty.dicole.net/?' + urllib.urlencode( {
            "url" : render_url,
            "upload" : upload_url,
            "width" : c["width"],
            "height" : c["height"],
            "auth" : cuty_secret,
            "javascript" : 1,
            "delay" : 2000
        } )

        http = httplib2.Http( timeout = 30 )
        resp, content = http.request( cuty_url )

        self.response.write( content )

class DebugUpdateHandler(webapp2.RequestHandler):
    def get(self):
        if has_wrong_auth(self):
            return
        c = current_config(self)

        futusome_url = form_futusome_update_url( self )

        render_url = 'https://' + os.environ['HTTP_HOST'] + '/renderawesome?' +  state_url_query(self)

        receive_url_abs = '/receive?' + state_url_query(self)
        upload_url = blobstore.create_upload_url( receive_url_abs )

        cuty_url = 'https://cuty.dicole.net/?' + urllib.urlencode( {
            "url" : render_url,
            "upload" : upload_url,
            "width" : c["width"],
            "height" : c["height"],
            "auth" : cuty_secret,
            "javascript" : 1,
            "delay" : 2000
        } )

        template_values = {
            'futusome_url' : futusome_url,
            'cuty_url' : cuty_url,
            'render_url' : render_url,
            'upload_url' : upload_url,
        }

        template = JINJA_ENVIRONMENT.get_template('updatedebug.jinja2')
        self.response.write(template.render(template_values))


class ReceiveHandler(blobstore_handlers.BlobstoreUploadHandler):
    def post(self):
        if has_wrong_auth(self):
            return

        upload_files = self.get_uploads('file')  # 'file' is file upload field in the form
        blob_info = upload_files[0]
        old_blob_key = GlobalData.fetch('blob_key_' + self.request.get('client'));
        GlobalData.store('blob_key_' + self.request.get('client'), str( blob_info.key() ) );
        if old_blob_key:
           blobstore.delete(old_blob_key)

        render_url = 'https://' + os.environ['HTTP_HOST'] + '/serve?' +  state_url_query(self)
        self.response.write("Image can be downloaded from " + render_url );

class ServeHandler(blobstore_handlers.BlobstoreDownloadHandler):
    def get(self):
        if has_wrong_auth(self):
            return

        resource = GlobalData.fetch('blob_key_' + self.request.get('client'))
        blob_info = blobstore.BlobInfo.get(resource)
        self.response.headers["Content-Type"] = "image/png"
        self.send_blob(blob_info)

class TestHandler(webapp2.RequestHandler):
    def get(self):
        if has_wrong_auth(self):
            return

        data = GlobalData.fetch('latest_data_' + self.request.get('client'));
        template_values = {
            "client" : self.request.get('client'),
            "auth" : self.request.get('auth'),
            "data" : data
        }
        template = JINJA_ENVIRONMENT.get_template('renderdebug.jinja2')
        self.response.write(template.render(template_values))

class TestUpdateHandler(webapp2.RequestHandler):
    def post(self):
        if has_wrong_auth(self):
            return

        GlobalData.store('latest_data_' + self.request.get('client'), self.request.get('data'));
        return self.redirect( '/test?' + state_url_query(self) );

class GlobalData(ndb.Model):
    data = ndb.StringProperty(indexed=False)

    @classmethod
    def fetch(cls, id ):
        model = GlobalData.get_by_id( id );
        if model:
            return model.data
        else:
            return ''

    @classmethod
    def store(cls, id, string ):
        model = GlobalData( id = id );
        model.data = string;
        model.put();
        return model.data;


app = webapp2.WSGIApplication([
    ('/renderawesome', RenderAwesomeHandler),
    ('/update', UpdateHandler),
    ('/receive', ReceiveHandler),
    ('/serve', ServeHandler),

    ('/debugupdate', DebugUpdateHandler),
    ('/test', TestHandler),
    ('/testupdate', TestUpdateHandler)
], debug=True)


