# -*- coding: utf-8 -*-
# BSD 2-Clause License
#
# Apprise - Push Notification Library.
# Copyright (c) 2024, Chris Caron <lead2gold@gmail.com>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

# Sign-up at https://wxpusher.zjiecode.com/
#
# Login and acquire your Token
#
import re
import json
import requests
from itertools import chain
from .base import NotifyBase
from ..url import PrivacyMode
from ..common import NotifyType
from ..common import NotifyFormat
from ..utils import parse_list
from ..utils import validate_regex
from ..locale import gettext_lazy as _


# Topics are always numerical
IS_TOPIC = re.compile(r'^\s*(?P<topic>[1-9][0-9]{0,20})\s*$')

# users always start with UID_
IS_USER = re.compile(
    r'^\s*(?P<full>(?P<prefix>UID_)(?P<user>[^\s]+))\s*$', re.I)


class WxPusherContentType:
    """
    Defines the different supported content types
    """
    TEXT = 0
    HTML = 1
    MARKDOWN = 2


class SubscriptionType:
    # Verify Subscription Time
    UNVERIFIED = 0
    PAID_USERS = 1
    UNSUBSCRIBED = 2


class NotifyWxPusher(NotifyBase):
    """
    A wrapper for WxPusher Notifications
    """

    # The default descriptive name associated with the Notification
    service_name = 'WxPusher'

    # The services URL
    service_url = 'https://wxpusher.zjiecode.com/'

    # The default protocol
    secure_protocol = 'wxpusher'

    # A URL that takes you to the setup/help of the specific protocol
    setup_url = 'https://github.com/caronc/apprise/wiki/Notify_wxpusher'

    # WxPusher notification endpoint
    notify_url = 'http://wxpusher.zjiecode.com/api/send/message'

    # Define object templates
    templates = (
        '{schema}://{token}/{targets}',
    )

    # Define our template tokens
    template_tokens = dict(NotifyBase.template_tokens, **{
        'token': {
            'name': _('App Token'),
            'type': 'string',
            'required': True,
            'regex': (r'^AT_[^\s]+$', 'i'),
            'private': True,
        },
        'target_topic': {
            'name': _('Target Topic'),
            'type': 'int',
            'map_to': 'targets',
        },
        'target_user': {
            'name': _('Target User ID'),
            'type': 'string',
            'regex': (r'^UID_[^\s]+$', 'i'),
            'map_to': 'targets',
        },
        'targets': {
            'name': _('Targets'),
            'type': 'list:string',
        },
    })

    # Define our template arguments
    template_args = dict(NotifyBase.template_args, **{
        'to': {
            'alias_of': 'targets',
        },
        'token': {
            'alias_of': 'token',
        },
    })

    # Used for mapping the content type to our output since Apprise supports
    # The same formats that WxPusher does.
    __content_type_map = {
        NotifyFormat.MARKDOWN: WxPusherContentType.MARKDOWN,
        NotifyFormat.TEXT: WxPusherContentType.TEXT,
        NotifyFormat.HTML: WxPusherContentType.HTML,
    }

    def __init__(self, token, targets=None, **kwargs):
        """
        Initialize WxPusher Object
        """
        super().__init__(**kwargs)

        # App Token (associated with WxPusher account)
        self.token = validate_regex(
            token, *self.template_tokens['token']['regex'])
        if not self.token:
            msg = 'An invalid WxPusher App Token ' \
                  '({}) was specified.'.format(token)
            self.logger.warning(msg)
            raise TypeError(msg)

        # Used for URL generation afterwards only
        self._invalid_targets = list()

        # For storing what is detected
        self._users = list()
        self._topics = list()

        # Parse our targets
        for target in parse_list(targets):
            # Validate targets and drop bad ones:
            result = IS_USER.match(target)
            if result:
                # store valid user
                self._users.append(result['full'])
                continue

            result = IS_TOPIC.match(target)
            if result:
                # store valid topic
                self._topics.append(int(result['topic']))
                continue

            self.logger.warning(
                'Dropped invalid WxPusher user/topic '
                '(%s) specified.' % target,
            )
            self._invalid_targets.append(target)

        return

    def send(self, body, title='', notify_type=NotifyType.INFO, **kwargs):
        """
        Perform WxPusher Notification
        """

        if not self._users and not self._topics:
            # There were no services to notify
            self.logger.warning(
                'There were no WxPusher targets to notify')
            return False

        # Prepare our headers
        headers = {
            'User-Agent': self.app_id,
            'Content-Type': 'application/json; charset=utf-8',
        }

        # Prepare our payload
        payload = {
            'appToken': self.token,
            'content': body,
            'summary': title,
            'contentType': self.__content_type_map[self.notify_format],
            'topicIds': self._topics,
            'uids': self._users,

            # unsupported at this time
            'verifyPay': False,
            'verifyPayType': 0,
            'url': None,
        }

        # Some Debug Logging
        self.logger.debug('WxPusher POST URL: {} (cert_verify={})'.format(
            self.notify_url, self.verify_certificate))
        self.logger.debug('WxPusher Payload: {}' .format(payload))

        # Always call throttle before any remote server i/o is made
        self.throttle()

        try:
            r = requests.post(
                self.notify_url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                verify=self.verify_certificate,
                timeout=self.request_timeout,
            )

            try:
                content = json.loads(r.content)

            except (AttributeError, TypeError, ValueError):
                # ValueError = r.content is Unparsable
                # TypeError = r.content is None
                # AttributeError = r is None
                content = {}

            if r.status_code == requests.codes.ok and \
                    content and content.get('success', False):

                # We're good!
                self.logger.info(
                    'Sent WxPusher notification to %d targets.' % (
                        len(self._users) + len(self._topics)))

            else:
                # We had a problem
                status_str = \
                    NotifyWxPusher.http_response_code_lookup(
                        r.status_code)

                self.logger.warning(
                    'Failed to send WxPusher notification: '
                    '{}{}error={}.'.format(
                        status_str,
                        ', ' if status_str else '',
                        r.status_code))

                self.logger.debug(
                    'Response Details:\r\n{}'.format(
                        content if content else r.content))

                # Mark our failure
                return False

        except requests.RequestException as e:
            self.logger.warning(
                'A Connection error occurred sending WxPusher '
                'notification.'
            )
            self.logger.debug('Socket Exception: %s' % str(e))

            return False

        return True

    def url(self, privacy=False, *args, **kwargs):
        """
        Returns the URL built dynamically based on specified arguments.
        """

        # Define any URL parameters
        params = self.url_parameters(privacy=privacy, *args, **kwargs)

        return '{schema}://{token}/{targets}/?{params}'.format(
            schema=self.secure_protocol,
            token=self.pprint(
                self.token, privacy, mode=PrivacyMode.Secret, safe=''),
            targets='/'.join(chain(
                [str(t) for t in self._topics], self._users,
                [NotifyWxPusher.quote(x, safe='')
                 for x in self._invalid_targets])),
            params=NotifyWxPusher.urlencode(params))

    def __len__(self):
        """
        Returns the number of targets associated with this notification
        """
        targets = len(self._users) + len(self._topics)
        return targets if targets > 0 else 1

    @staticmethod
    def parse_url(url):
        """
        Parses the URL and returns enough arguments that can allow
        us to re-instantiate this object.

        """
        results = NotifyBase.parse_url(url, verify_host=False)
        if not results:
            # We're done early as we couldn't load the results
            return results

        # Get our entries; split_path() looks after unquoting content for us
        # by default
        results['targets'] = NotifyWxPusher.split_path(results['fullpath'])

        # App Token
        if 'token' in results['qsd'] and len(results['qsd']['token']):
            # Extract the App token from an argument
            results['token'] = \
                NotifyWxPusher.unquote(results['qsd']['token'])
        else:
            # The hostname is our source number
            results['token'] = NotifyWxPusher.unquote(results['host'])

        # Support the 'to' variable so that we can support rooms this way too
        # The 'to' makes it easier to use yaml configuration
        if 'to' in results['qsd'] and len(results['qsd']['to']):
            results['targets'] += \
                NotifyWxPusher.parse_list(results['qsd']['to'])

        return results
