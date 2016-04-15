import os
import json
import base64

from datetime import datetime
from flask import request, g, Blueprint, make_response, Response
from flask import jsonify as flask_jsonify
from flask.ext.restful import reqparse
from sqlalchemy import asc, func
from sqlalchemy.orm.exc import NoResultFound

from nylas.logging import get_logger
log = get_logger()

from inbox.models import (Account, Message, Block, Part, Thread, Namespace,
                          Contact, Calendar, Event, Transaction,
                          DataProcessingCache, Category, MessageCategory)
from inbox.models.backends.generic import GenericAccount
from inbox.api.kellogs import APIEncoder
from inbox.api import filtering
from inbox.api.validation import (valid_account, get_attachments, get_calendar,
                                  get_recipients, get_draft, valid_public_id,
                                  valid_event, valid_event_update, timestamp,
                                  bounded_str, view, strict_parse_args,
                                  limit, offset, ValidatableArgument,
                                  strict_bool, validate_draft_recipients,
                                  valid_delta_object_types, valid_display_name,
                                  noop_event_update, valid_category_type,
                                  comma_separated_email_list)
from inbox.config import config
from inbox.ignition import engine_manager
from inbox.models.action_log import schedule_action
from inbox.models.session import new_session, session_scope, global_session_scope
from inbox.search.base import get_search_client, SearchBackendException
from inbox.transactions import delta_sync
from inbox.auth.generic import GenericAuthHandler
from inbox.auth.base import handler_from_provider
from inbox.basicauth import NotSupportedError
from inbox.api.err import err, APIException, NotFoundError, InputError

app = Blueprint(
    'auth_api',
    __name__,
    url_prefix='/auth')
    
@app.before_request
def start():
#   engine = engine_manager.get_for_id(g.namespace_id)
#   g.db_session = new_session(engine)
#   g.namespace = Namespace.get(g.namespace_id, g.db_session)

#   g.log = log.new(endpoint=request.endpoint,
#       account_id=g.namespace.account_id)
#  g.parser = reqparse.RequestParser(argument_class=ValidatableArgument)
#  g.encoder = APIEncoder()
   return

@app.after_request
def finish(response):
    if response.status_code == 200 and hasattr(g, 'db_session'):  # be cautions
        g.db_session.commit()
    if hasattr(g, 'db_session'):
        g.db_session.close()
    return response
    
@app.errorhandler(NotImplementedError)
def handle_not_implemented_error(error):
    response = flask_jsonify(message="API endpoint not yet implemented.",
                             type='api_error')
    response.status_code = 501
    return response
    
@app.errorhandler(InputError)
def handle_input_error(error):
    response = flask_jsonify(message=str(error), type='api_error')
    response.status_code = 400
    return response

@app.route('/')
def index():
    return """
    <html><body>
       Check out the <strong><pre style="display:inline;">docs</pre></strong>
       folder for how to use this API.
    </body></html>
    """

def authorize(email_address, provider, auth_data):
    auth_info = {}
    auth_info['provider'] = provider

    shard_id = 0 << 48

    with session_scope(shard_id) as db_session:
        account = db_session.query(Account).filter_by(
            email_address=email_address).first()

    auth_handler = handler_from_provider(provider)
    auth_response = auth_handler.auth(auth_data)

    if auth_response is False:
        return err(403, 'Authorizatison error!')

    auth_info.update(auth_response)
    account = auth_handler.create_account(email_address, auth_info)

    try:
        if auth_handler.verify_account(account):
            db_session.add(account)
            db_session.commit()
    except NotSupportedError as e:
        return err(406, 'Provider not supported!')

    return g.encoder.jsonify({"msg": "Authorization success"})
    
@app.route('/custom', methods=['POST'])
def custom_auth():
    imap_server_host = 'smtp.e-casework.com'
    imap_server_port = 993
    smtp_server_host = 'smtp.e-casework.com'
    smtp_server_port = 587
    data = request.get_json(force=True)

    args = []
    if not data.get('email'):
        return err(406, 'Email address is required!')
 
    if not data.get('password'):
        return err(406, 'Password is required!')

 
    return authorize(data.get('email'), 'custom', {
                     "provider_type": "custom", "email_address": data.get('email'),
                     "password": data.get('password'), "imap_server_host": imap_server_host,
                     "imap_server_port": imap_server_port, "smtp_server_host": smtp_server_host,
                     "smtp_server_port": smtp_server_port})