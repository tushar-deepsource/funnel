from __future__ import annotations

from string import Formatter
from typing import Dict, Optional, Pattern, cast
import re

from flask import Flask

__all__ = [
    'SmsTemplate',
    'WebOtpTemplate',
    'OneLineTemplate',
    'TwoLineTemplate',
    'MessageTemplate',
]

# --- Registered template processor ----------------------------------------------------

# This list of chars is from https://archive.is/XJJHV via Airtel.
# Not currently used because the documentation is unclear on how to use it
dlt_exempted_chars_re = re.compile('[~`!@#$%^&*()_+={}\\[\\]|\\\\/:;"\'<>,.?-]')

_var_variant_re = re.compile(r'{\s*#\s*var\s*#\s*}', re.IGNORECASE)
_var_repeat_re = re.compile('({#.*?#})+')

#: The maximum number of characters that can appear under one {#var#}
#: Unclear in documentation: are exempted characters excluded from this length limit?
VAR_MAX_LENGTH = 30


class SmsTemplate:
    r"""
    SMS template validator and formatter, for DLT registered SMS in India.

    To use, create a subclass with the registered and Python templates, and optionally
    override :meth:process to process variables. The registered and Python templates are
    validated to match each other when the class is created::

        class MyTemplate(SmsTemplate):
            registered_template = "Insert {#var#} here"
            template = "Insert {var} here"

            var: str  # Declare variable type like this

            # Optional processor
            def process(self) -> None:
                assert isinstance(self.var, str)

    The template can be used in a single pass::

        >>> str(MyTemplate(var="sample"))
        'Insert sample here'

    Or it can be constructed one variable at a time::

        >>> msg = MyTemplate()
        >>> msg.var = "sample"
        >>> msg.var
        'sample'
        >>> msg.text
        'Insert sample here'

    Format fields for the Python template can be set and accessed directly from the
    class instance. The formatted string is available as :property:`text`, or by casting
    the template object to a string.

    Templates can be split into a base "registered template" class and an "application
    template" subclass. This pattern allows for multiple application templates riding
    atop a single generic registered template, and also for localization. The text in
    the registered template cannot be localized::

        class RegisteredTemplate(SmsTemplate):
            registered_template = '{#var#}{#var#}{#var#}{#var#}\n\n{#var#} to stop'
            template = '{content}\n\n{unsubscribe_url} to stop'

            @property
            def unsubscribe_url(self):
                return 'https://unsubscribe.example/'

            def available_var_len(self):
                '''Return available length for variables.'''
                return self.template_var_len - len(self.unsubscribe_url)


        class MessageTemplate(RegisteredTemplate):
            @property
            def content(self):
                return _("You have a message from {user}").format(user=self.user)

            def process(self):
                '''Truncate variables to fit available length.'''
                alen = self.available_var_len()
                if len(self.user) > alen:
                    self.user = self.user[: alen - 1] + '…'


        >>> str(MessageTemplate("Rincewind"))
        'You have a message from Rincewind\n\nhttps://unsubscribe.example/ to stop'
    """

    #: Registered entity id
    registered_entityid: Optional[str] = None
    #: Registered template id
    registered_templateid: Optional[str] = None
    #: Registered template, using `{#var#}` where variables should appear
    registered_template: str = ""
    #: Python template, with formatting variables as {var}
    template: str = ""

    #: Autogenerated regex version of registered template
    registered_template_re: Pattern = re.compile('')  # Will be replaced in subclasses
    #: Autogenerated count of static characters in registered template
    registered_template_static_len: int = 0  # Will be replaced in subclasses
    #: Autogenerated count of characters available in variables
    registered_template_var_len: int = 0  # Will be replaced in subclasses

    # Type hints for mypy. These attributes are set in __init__
    _text: Optional[str]
    _format_kwargs: Dict[str, object]
    template_static_len: int
    template_var_len: int

    def __init__(self, **kwargs) -> None:
        """Initialize template with variables."""
        object.__setattr__(self, '_text', None)
        object.__setattr__(self, '_format_kwargs', {})
        # Calculate the formatted length before variables are inserted. Subclasses
        # can use this to truncate variables to fit. We do this in the instance and not
        # the class so that subclasses can support localization of static text by
        # defining those "variables" as properties on the class. Since no variables
        # have been stored yet, this call to vformat will invoke self.__getitem__, which
        # will return '' for unknown keys.
        object.__setattr__(
            self,
            'template_static_len',
            # vformat only needs __getitem__, so ignore mypy's warning about arg type.
            # The expected type is Mapping[str, Any]
            len(Formatter().vformat(self.template, (), self)),  # type: ignore[arg-type]
        )
        # Now set the length available for variables by comparing with the registered
        # template. The Python template may have static text where the registered
        # template has a variable, so we get the difference. This value can be used by
        # :meth:`process` to truncate variables to fit.
        object.__setattr__(
            self,
            'template_var_len',
            self.registered_template_var_len
            + self.registered_template_static_len
            - self.template_static_len,
        )
        # Next, store real format field values
        self._format_kwargs.update(kwargs)

    def available_var_len(self):
        """
        Available length for variable characters, to truncate as necessary.

        Subclasses may override this to subtract variables that cannot be truncated.
        """
        return self.template_var_len

    def process(self) -> None:
        """Process variables (subclasses may override as necessary)."""

    def format(self) -> None:  # noqa: A003
        """Format template with variables."""
        self.process()
        object.__setattr__(
            self,
            '_text',
            # vformat only needs __getitem__, so ignore mypy's warning about arg type.
            # The expected type is Mapping[str, Any]
            Formatter().vformat(self.template, (), self),  # type: ignore[arg-type]
        )

    @property
    def text(self) -> str:
        if self._text is None:
            self.format()
        # self.format() ensures `_text` is str, but mypy doesn't know
        return cast(str, self._text)

    def __str__(self) -> str:
        """Return SMS text as string."""
        return self.text

    def __repr__(self) -> str:
        """Return a representation of self."""
        return f'<{self.__class__.__name__} {self.text!r}>'

    def __getattr__(self, attr: str):
        """Get a format variable."""
        try:
            return self._format_kwargs[attr]
        except KeyError:
            raise AttributeError(attr)

    def __getitem__(self, key: str):
        """Get a format variable via dictionary access, defaulting to ''."""
        return getattr(self, key, '')

    def __setattr__(self, attr: str, value) -> None:
        """Set a format variable."""
        self._format_kwargs[attr] = value
        object.__setattr__(self, '_text', None)

    @classmethod
    def validate_registered_template(cls) -> None:
        """Validate the Registered template as per documented rules."""
        # 1. Confirm the template is within 2000 characters
        if len(cls.registered_template) > 2000:
            raise ValueError(
                f"Registered template must be within 2000 chars"
                f" (currently {len(cls.registered_template)} chars)"
            )

        # 2. Check for incorrect reprentations of `{#var#}` (spaces, casing)
        for varmatch in _var_variant_re.findall(cls.registered_template):
            if varmatch != '{#var#}':
                raise ValueError(
                    f"Registered template must use {{#var#}}, not {varmatch}"
                )
        cls.registered_template_static_len = len(
            _var_repeat_re.sub('', cls.registered_template)
        )
        cls.registered_template_var_len = (
            cls.registered_template.count('{#var#}') * VAR_MAX_LENGTH
        )

        # 3. Create a compiled regex for the registered template that replaces
        #    repetitions of '{#var#}' with a '.*?'. This is used to validate the Python
        #    template. Registered templates need to have repetitions of '{#var#}' to
        #    increase the number of characters allowed (30 per instance), but as per
        #    current understanding of the spec, the length limit is shared across the
        #    template and not per var. Therefore we use '.*?' instead of '.{0,30}?' and
        #    leave the length validation and truncation to :meth:`process`
        cls.registered_template_re = re.compile(
            re.escape(_var_repeat_re.sub('{#var#}', cls.registered_template)).replace(
                # `re.escape` will convert '{#var#}' to r'\{\#var\#\}'
                r'\{\#var\#\}',
                '.*?',
            ),
            re.DOTALL,  # Let .*? include newlines, as that is valid in variables
        )

    @classmethod
    def validate_template(cls) -> None:
        """Validate that the Python template matches the registered template."""
        # 1. Confirm template does not use format fields that conflict with class
        #    members, or are positional instead of keyword.
        for _literal_text, field_name, _format_spec, _conversion in Formatter().parse(
            cls.template
        ):
            if field_name is not None:
                if field_name == '' or field_name.isdigit():
                    raise ValueError("Templates cannot have positional fields")
                if (
                    field_name in ('_text', '_format_kwargs')
                    or field_name in SmsTemplate.__dict__
                ):
                    raise ValueError(
                        f"Template field '{field_name}' in {cls.__name__} is reserved"
                        f" and cannot be used"
                    )

        # 2. Match regex against Python template
        if cls.registered_template_re.fullmatch(cls.template) is None:
            raise ValueError(
                f"Python template does not match registered template in {cls.__name__}"
                f"\nRegistered template: {cls.registered_template!r}"
                f"\nAs regex: {cls.registered_template_re!r}"
                f"\nTemplate: {cls.template!r}"
            )

    @classmethod
    def validate_no_entity_template_id(cls) -> None:
        if cls.registered_entityid is not None or cls.registered_templateid is not None:
            raise TypeError(
                "Registered entity id and template id are not public information and"
                " must be in config. Use init_app to load config"
            )

    def __init_subclass__(cls) -> None:
        """Validate templates in subclasses."""
        super().__init_subclass__()
        cls.validate_no_entity_template_id()
        cls.validate_registered_template()
        cls.validate_template()

    @classmethod
    def init_subclass_config(cls, app: Flask, config: Dict[str, str]) -> None:
        """Recursive init for setting template ids in subclasses."""
        for subcls in cls.__subclasses__():
            subcls_config_name = ''.join(
                ['_' + c.lower() if c.isupper() else c for c in subcls.__name__]
            ).lstrip('_')
            templateid = config.get(subcls_config_name)
            if not templateid:
                # No template id provided. If class already has a templateid from
                # parent class, let this pass. If not, raise a warning.
                if not cls.registered_templateid:
                    app.logger.warning(
                        "App config is missing SMS_DLT_TEMPLATE_IDS['%s'] for template"
                        " %s",
                        subcls_config_name,
                        subcls.__name__,
                    )
            else:
                # Set the template id from config
                subcls.registered_templateid = templateid
            # Recursively configure subclasses of this subclass
            subcls.init_subclass_config(app, config)

    @classmethod
    def init_app(cls, app: Flask) -> None:
        """Set Registered entity id and template ids from app config."""
        cls.registered_entityid = app.config.get('SMS_DLT_ENTITY_ID')
        cls.init_subclass_config(app, app.config.get('SMS_DLT_TEMPLATE_IDS', {}))


# --- Registered templates used by this app --------------------------------------------


class WebOtpTemplate(SmsTemplate):
    """Template for Web OTPs."""

    registered_template = (
        'OTP is {#var#} for Hasgeek.\n\nNot you? Block misuse: {#var#}\n\n'
        '@{#var#} #{#var#}'
    )
    template = (
        'OTP is {otp} for Hasgeek.\n\nNot you? Block misuse: {helpline_text}\n\n'
        '@{domain} #{otp}'
    )


class OneLineTemplate(SmsTemplate):
    """Template for single line messages."""

    registered_template = '{#var#}{#var#}{#var#}{#var#}\n\n{#var#} to stop - Hasgeek'
    template = '{text1} {url}\n\n\n{unsubscribe_url} to stop - Hasgeek'

    text1: str
    url: str
    unsubscribe_url: str

    def available_var_len(self):
        """Discount the two URLs from available length."""
        return self.template_var_len - len(self.url) - len(self.unsubscribe_url)

    def process(self) -> None:
        """Truncate text1 to fit."""
        max_text_length = self.available_var_len()
        if len(self.text1) > max_text_length:
            self.text1 = self.text1[: max_text_length - 1] + '…'


class TwoLineTemplate(SmsTemplate):
    """Template for double line messages."""

    registered_template = (
        '{#var#}{#var#}\n\n{#var#}{#var#}\n\n{#var#} to stop - Hasgeek'
    )
    template = '{text1}\n\n{text2} {url}\n\n\n{unsubscribe_url} to stop - Hasgeek'

    text1: str
    text2: str
    url: str
    unsubscribe_url: str

    def available_var_len(self):
        """Discount the two URLs from available length."""
        return self.template_var_len - len(self.url) - len(self.unsubscribe_url)

    def process(self) -> None:
        """Truncate text1 and text2 to fit."""
        max_text_length = self.available_var_len()
        # `int()` always discards fractional values, so 100*0.33 + 100*0.66 == 99
        max_text1_length = int(max_text_length * 0.33)
        max_text2_length = int(max_text_length * 0.66)
        if len(self.text1) > max_text1_length:
            self.text1 = self.text1[: max_text1_length - 1] + '…'
        if len(self.text2) > max_text2_length:
            self.text2 = self.text2[: max_text2_length - 1] + '…'


class MessageTemplate(OneLineTemplate):
    template = '{message}\n\n\n{unsubscribe_url} to stop - Hasgeek'

    message: str
    unsubscribe_url: str

    def available_var_len(self):
        """Discount the unsubscribe URL from available length."""
        return self.template_var_len - len(self.unsubscribe_url)

    def process(self) -> None:
        """Truncate message to fit."""
        max_text_length = self.available_var_len()
        if len(self.message) > max_text_length:
            self.message = self.message[: max_text_length - 1] + '…'
