# The MIT License (MIT)
# Copyright (c) 2022 by the xcube team and contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import threading
from typing import Any, Dict, List, Optional, Mapping, Iterator, Union, Tuple

import fsspec

from xcube.constants import LOG
from xcube.server.api import ApiContext
from xcube.server.api import ApiError
from xcube.server.api import Context
from xcube.server.config import get_base_dir
from xcube.server.config import resolve_config_path
from xcube.util.perf import measure_time_cm
from xcube.version import version
from xcube.webapi.auth import AuthContext


class ResourcesContext(ApiContext):

    def __init__(self, server_ctx: Context):
        super().__init__(server_ctx)
        # noinspection PyTypeChecker
        self._auth_ctx: AuthContext = server_ctx.get_api_ctx("auth")
        assert isinstance(self._auth_ctx, AuthContext)
        self._base_dir = get_base_dir(self.config)
        self._prefix = normalize_prefix(self.config.get("prefix", ""))
        self._trace_perf = self.config.get("trace_perf", False)
        self._rlock = threading.RLock()

    @property
    def auth_ctx(self) -> AuthContext:
        return self._auth_ctx

    @property
    def base_dir(self) -> str:
        return self._base_dir

    @property
    def rlock(self) -> threading.RLock:
        return self._rlock

    @property
    def trace_perf(self) -> bool:
        return self._trace_perf

    @property
    def measure_time(self):
        return measure_time_cm(disabled=not self.trace_perf, logger=LOG)

    @property
    def can_authenticate(self) -> bool:
        """
        Test whether the user can authenticate.
        Even if authentication service is configured, user authentication
        may still be optional. In this case the server will publish
        the resources configured to be free for everyone.
        """
        return self._auth_ctx.can_authenticate

    @property
    def must_authenticate(self) -> bool:
        """
        Test whether the user must authenticate.
        """
        return self._auth_ctx.must_authenticate

    @property
    def access_control(self) -> Dict[str, Any]:
        return self.config.get('AccessControl', {})

    @property
    def required_scopes(self) -> List[str]:
        return self.access_control.get('RequiredScopes', [])

    def get_service_url(self, base_url: Optional[str], *path: str):
        base_url = base_url or ''
        # noinspection PyTypeChecker
        path_comp = '/'.join(path)
        if self._prefix:
            return base_url + self._prefix + '/' + path_comp
        else:
            return base_url + '/' + path_comp

    def get_config_path(self,
                        config: Mapping[str, Any],
                        config_name: str,
                        path_entry_name: str = 'Path') -> str:
        path = config.get(path_entry_name)
        if not path:
            raise ApiError.InvalidServerConfig(
                f"Missing entry {path_entry_name!r} in {config_name}"
            )
        return self.resolve_config_path(path)

    def resolve_config_path(self, path: str) -> str:
        return resolve_config_path(self.config, path)

    def load_file(self,
                  path: str,
                  mode: str = "rb",
                  encoding: str = "utf-8") -> Union[str, bytes]:
        with self.open_file(path, mode=mode, encoding=encoding) as fp:
            return fp.read()

    def open_file(self,
                  path: str,
                  mode: str = "rb",
                  encoding: str = "utf-8") -> fsspec.core.OpenFile:
        path = self.resolve_config_path(path)
        return fsspec.open(path, mode=mode, encoding=encoding)

    def eval_config_value(self, value: Any) -> Any:
        """Evaluate expressions in the given *value* if it is
        a string. If *value* is a dict or list, then the method
        is called recursively and applied to the values of the
        dict or the items of the list. In this case a dict or list
        will be returned.
        Expressions are any string between non-quoted "${" and "}".
        An iterator is returned comprising non-expression
        parts as well as parts evaluated in the context of this
        context object.
        """
        if isinstance(value, dict):
            return {k: self.eval_config_value(v)
                    for k, v in value.items()}
        if isinstance(value, list):
            return [self.eval_config_value(v)
                    for v in value]
        if isinstance(value, str):
            return self._eval_config_str_value(value)
        return value

    def _eval_config_str_value(self, value: str) -> Any:
        values = list(self._eval_value(value))
        if len(values) > 1:
            return "".join([str(v) for v in values])
        elif len(values) == 1:
            return values[0]
        return value

    def _eval_value(self, value: str) -> Iterator[Any]:
        """Evaluate expressions in a given string *value*.
        Expressions are any string between non-quoted "${" and "}".
        An iterator is returned comprising non-expression
        parts as well as parts evaluated in the context of this
        context object.
        """
        for token in self._tokenize_value(value):
            if isinstance(token, tuple):
                expression, = token
                yield eval(expression, None, self.new_eval_env())
            else:
                yield token

    def new_eval_env(self) -> Dict[str, Any]:
        return dict(
            ctx=self,
            base_dir=self.base_dir,
            load_file=self.load_file,
            open_file=self.open_file,
            resolve_config_path=self.resolve_config_path
        )

    @classmethod
    def _tokenize_value(cls, value: str) -> Iterator[Union[str, Tuple[str]]]:
        """Tokenize a string value. Tokens are either strings or 1-tuples
        that contain a string-expression to be evaluated. String-expressions
        are any strings between non-quoted "${" and "}".
        """
        n = len(value)
        i0 = 0
        sqs = False
        dqs = False
        es = False
        for i in range(n):
            c = value[i]
            if c == "\\":
                continue
            elif c == "'" and not dqs:
                sqs = not sqs
            elif c == '"' and not sqs:
                dqs = not dqs
            elif c == '$' and not (sqs or dqs or es):
                if i < n - 1 and value[i + 1] == '{':
                    if i0 < i:
                        yield value[i0:i]  # Return a str.
                    es = True
                    i0 = i + 2
                    i += 1
            elif c == '}' and es:
                es = False
                yield value[i0:i],  # Yes, return a 1-tuple.
                i0 = i + 1
        if i0 == 0:
            yield value
        elif i0 < n:
            yield value[i0:n]  # Return a str.


def normalize_prefix(prefix: Optional[str]) -> str:
    if not prefix:
        return ''

    prefix = prefix.replace('${name}', 'xcube')
    prefix = prefix.replace('${version}', version)
    prefix = prefix.replace('//', '/').replace('//', '/')

    if prefix == '/':
        return ''

    if not prefix.startswith('/'):
        prefix = '/' + prefix

    if prefix.endswith('/'):
        prefix = prefix[0:-1]

    return prefix
