import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar, Optional, Union

import arrow
from pydantic import GetCoreSchemaHandler, field_serializer, field_validator
from pydantic_core import core_schema

import flexible_datetime.pydantic_arrow  # Need to import this module to patch arrow.Arrow
from flexible_datetime.flexible_datetime import FlexDateTime
from flexible_datetime.time_utils import infer_time_format

FlextimeInput = Union[str, FlexDateTime, datetime, arrow.Arrow, dict, "flextime", None]


class OutputFormat(StrEnum):
    """
    Enum for the output formats of flextime.

    minimal_datetime: Serialize as shortest possible datetime format.
        Examples:
            YYYY, YYYY-MM, YYYY-MM-DD, YYYY-MM-DD HH, YYYY-MM-DD HH:mm, YYYY-MM-DD HH:mm:ss

    datetime: Serialize as full datetime format.
        Example: YYYY-MM-DD HH:mm:ss

    flex: Serialize as JSON-compatible format.
        Example: {"dt": "2023-06-29T12:30:45+00:00", "mask": "0011111"}

    component_json: Serialize as JSON-compatible format with masked components.
        Example: {"year": 2023, "month": 6, "day": 29, "hour": 12, "minute": 30, "second": 45, "millisecond": 0}
    """

    minimal_datetime = "minimal_datetime"
    datetime = "datetime"
    flex = "flex"
    components = "components"


class flextime:

    _dt_formats: ClassVar[dict[str, str]] = {
        "YYYY": "year",
        "MM": "month",
        "DD": "day",
        "HH": "hour",
        "mm": "minute",
        "ss": "second",
        "S": "millisecond",
        "SS": "millisecond",
        "SSS": "millisecond",
        "SSSS": "millisecond",
        "SSSSS": "millisecond",
        "SSSSSS": "millisecond",
    }
    _mask_fields: ClassVar[dict[str, None]] = {
        "year": None,
        "month": None,
        "day": None,
        "hour": None,
        "minute": None,
        "second": None,
        "millisecond": None,
    }

    _default_output_format: ClassVar[OutputFormat] = OutputFormat.minimal_datetime

    def __init__(self, *args: FlextimeInput, **kwargs: Any):
        self.dt = arrow.utcnow()
        self.mask = {
            "year": False,
            "month": False,
            "day": False,
            "hour": False,
            "minute": False,
            "second": False,
            "millisecond": False,
        }

        self._output_format = self._default_output_format
        if args and args[0] is None:
            raise ValueError("Cannot parse None as a flextime.")
        if not args and not kwargs:
            return  # default values
        if args:
            if isinstance(args[0], dict):
                ## handle dict input
                d = args[0]
                is_dict_format = any(k in d for k in self._mask_fields)
                if "dt" not in kwargs and is_dict_format:
                    ## {"year": 2023, "month": 6, "day": 29}
                    dt, mask = self._components_from_dict(d)
                    self.dt = dt
                    self.mask = mask
                else:
                    self.dt = arrow.get(d["dt"])
                    if "mask" in d and isinstance(d["mask"], dict):
                        ## {"dt": "2023-06-29T12:30:45+00:00", "mask": {"year": False,..."millisecond": True}}
                        self.mask = d["mask"]
                    elif "mask" in d and isinstance(d["mask"], str):
                        ## {"dt": "2023-06-29T12:30:45+00:00", "mask": "0011111"}
                        self.mask = self.binary_to_mask(d["mask"])
            elif isinstance(args[0], str):
                ## handle string input,"2023", "2023-06-29T12:30:45+00:00"
                dt, mask = self._components_from_str(args[0])
                self.dt = dt
                self.mask = mask
            elif isinstance(args[0], arrow.Arrow):
                ## handle arrow.Arrow input
                self.dt = args[0]
            elif isinstance(args[0], flextime):
                ## handle flextime input
                self.dt = args[0].dt
                self.mask = args[0].mask
            elif isinstance(args[0], datetime):
                ## handle datetime input
                self.dt = arrow.get(args[0])
            elif isinstance(args[0], FlexDateTime):
                ## handle FlexDateTime input
                self.dt = args[0].dt
                self.mask = args[0].mask
            else:
                raise ValueError(f"Unsupported input: {args}")
            return
        ## handle kwargs input
        if "dt" in kwargs:
            self.dt = arrow.get(kwargs["dt"])
            if "mask" in kwargs:
                if isinstance(kwargs["mask"], dict):
                    self.mask = kwargs["mask"]
                elif isinstance(kwargs["mask"], str):
                    self.mask = self.binary_to_mask(kwargs["mask"])
                else:
                    raise ValueError(f"Invalid mask: {kwargs['mask']}")
                print(self.mask)
        else:
            raise NotImplementedError(f"Unsupported input: {args} {kwargs}")

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        """
        Defines the Pydantic core schema for flextime
        """

        def flextime_serialization(value: flextime, _, info) -> str:
            return str(value)

        return core_schema.no_info_after_validator_function(
            function=cls.validate,
            schema=core_schema.union_schema(
                [
                    core_schema.str_schema(),
                    core_schema.dict_schema(),
                    core_schema.is_instance_schema(flextime),
                    core_schema.is_instance_schema(datetime),
                    core_schema.is_instance_schema(arrow.Arrow),
                    core_schema.is_instance_schema(cls),
                    core_schema.no_info_plain_validator_function(cls),
                ]
            ),
            serialization=core_schema.wrap_serializer_function_ser_schema(
                flextime_serialization, info_arg=True
            ),
        )

    @classmethod
    def validate(cls, value) -> "flextime":
        if isinstance(value, flextime):
            return value
        return flextime(value)

    @staticmethod
    def infer_format(date_str: str) -> str:
        return infer_time_format(date_str)

    @classmethod
    def mask_to_binary(cls, mask: dict) -> str:
        return "".join(["1" if mask[field] else "0" for field in cls._mask_fields])

    @classmethod
    def binary_to_mask(cls, binary_str: str) -> dict:
        return {field: bool(int(bit)) for field, bit in zip(cls._mask_fields, binary_str)}

    @field_serializer("mask")
    def serialize_mask(self, mask: dict) -> str:
        return self.mask_to_binary(mask)

    @field_validator("mask", mode="before")
    def deserialize_mask(cls, value):
        if isinstance(value, str):
            return cls.binary_to_mask(value)
        return value

    @classmethod
    def from_str(cls, date_str: str, input_fmt: Optional[str] = None) -> "flextime":
        """
        Creates a flextime instance from a string.
        """
        dt, mask = cls._components_from_str(date_str, input_fmt)
        return cls(dt=dt, mask=mask)

    @classmethod
    def from_datetime(cls, dt: datetime) -> "flextime":
        """
        Creates a flextime instance from a datetime.
        """
        return cls(dt=dt)

    @classmethod
    def _components_from_str(cls, date_str: str, input_fmt: Optional[str] = None):
        """
        Creates the components of a flextime instance from a string.
        """

        try:
            dt = arrow.get(date_str, input_fmt) if input_fmt else arrow.get(date_str)
        except (arrow.parser.ParserError, ValueError):
            raise ValueError(f"Invalid date string: {date_str}")
        mask = {field: False for field in cls._mask_fields}

        input_fmt = input_fmt or cls.infer_format(date_str)

        # Determine which parts were provided by checking the input format
        provided_parts = set()
        for fmt in cls._dt_formats:
            if fmt in input_fmt:
                provided_parts.add(cls._dt_formats[fmt])

        for part in cls._mask_fields:
            mask[part] = part not in provided_parts

        return dt, mask

    @classmethod
    def _components_from_dict(cls, datetime_dict):
        # Provide default values for missing keys
        components = {
            "year": 1970,
            "month": 1,
            "day": 1,
            "hour": 0,
            "minute": 0,
            "second": 0,
            "microsecond": 0,
            "tzinfo": "UTC",
        }
        mask = {k: True for k in cls._mask_fields}

        # Convert milliseconds to microseconds if present
        if "millisecond" in datetime_dict:
            datetime_dict["microsecond"] = datetime_dict.pop("millisecond") * 1000

        # Update components with provided values
        components.update(datetime_dict)

        # Apply mask
        for k in datetime_dict:
            mask[k] = False

        ## handle microseconds
        if "microsecond" in datetime_dict:
            mask["millisecond"] = False

        dt = arrow.Arrow(**components)
        return dt, mask

    @classmethod
    def from_dict(cls, datetime_dict):
        dt, mask = cls._components_from_dict(datetime_dict)
        return cls(dt=dt, mask=mask)

    def apply_mask(self, **kwargs) -> None:
        """
        Updates the mask with the provided keyword arguments.
        """
        self.mask.update(kwargs)

    def clear_mask(self) -> None:
        """
        Clears the mask.
        """
        self.mask = {
            "year": False,
            "month": False,
            "day": False,
            "hour": False,
            "minute": False,
            "second": False,
            "millisecond": False,
        }

    def use_only(self, *args, **kwargs) -> None:
        """
        Use only the specified elements (unmasks them).
        """
        self.clear_mask()
        nargs = args[0] if args and isinstance(args[0], list) else args
        new_mask = {k: True for k in nargs}
        new_mask.update(kwargs)
        for k in self.mask:
            if k not in new_mask:
                self.mask[k] = True
        # for a in args:
        #     self.mask[a.lower()] = True

    def toggle_mask(self, **kwargs) -> None:
        """
        Toggles the mask for the provided keyword arguments.
        """
        for key in kwargs:
            self.mask[key] = not self.mask[key]

    @property
    def year(self):
        return self.dt.year

    @property
    def month(self):
        return self.dt.month

    @property
    def day(self):
        return self.dt.day

    @property
    def hour(self):
        return self.dt.hour

    @property
    def minute(self):
        return self.dt.minute

    @property
    def second(self):
        return self.dt.second

    @property
    def millisecond(self):
        return self.dt.microsecond // 1000

    @property
    def microsecond(self):
        return self.dt.microsecond

    def to_minimal_datetime(self, output_fmt: Optional[str] = None) -> str:
        """
        Returns the string representation of the datetime, considering the mask.
        Args:
            output_fmt: The format of the output string.
                Defaults to ISO 8601 format "YYYY-MM-DDTHH:mm:ss.SSSSSS%z", but masking will remove parts of the string.

        Returns:
            The string representation of the datetime.
        """
        if not self.dt:
            return "Invalid datetime"

        output_str = output_fmt or "YYYY-MM-DDTHH:mm:ss.SSSSSS%z"

        # Handle each part
        for fmt, part in flextime._dt_formats.items():
            if part == "millisecond":
                # Format milliseconds/microseconds correctly
                microseconds = self.dt.microsecond
                if "SSSSSS" in output_str:
                    replacement = f"{microseconds:06d}"
                elif "SSSSS" in output_str:
                    replacement = f"{microseconds:06d}"[:5]
                elif "SSSS" in output_str:
                    replacement = f"{microseconds:06d}"[:4]
                elif "SSS" in output_str:
                    replacement = f"{microseconds:06d}"[:3]
                elif "SS" in output_str:
                    replacement = f"{microseconds // 1000:03d}"[:2]
                elif "S" in output_str:
                    replacement = f"{microseconds // 1000:03d}"[:1]
                else:
                    replacement = ""
                if self.mask[part]:
                    replacement = ""
                output_str = re.sub(r"S{1,6}", replacement, output_str)
            elif part == "tzinfo":
                # Handle timezone offset
                if self.dt.tzinfo:
                    offset = self.dt.utcoffset()
                    if offset:
                        hours, remainder = divmod(offset.total_seconds(), 3600)
                        minutes = remainder // 60
                        replacement = f"{hours:+03.0f}:{minutes:02.0f}"
                    else:
                        replacement = "+00:00"
                else:
                    replacement = ""
                if self.mask[part]:
                    replacement = ""
                output_str = output_str.replace("%z", replacement)
            else:
                value = getattr(self.dt, part)
                replacement = (
                    f"{value:02d}" if fmt in ["MM", "DD", "HH", "mm", "ss"] else str(value)
                )
                replacement = replacement if not self.mask[part] else ""
                output_str = output_str.replace(fmt, replacement)

        # Remove unnecessary separators while preserving date and time structure
        output_str = re.sub(r"(?<=\d)(\s|-|:|T)(?=\d)", r"\1", output_str)
        output_str = re.sub(r"\s+", " ", output_str).strip()
        output_str = re.sub(r"-+", "-", output_str)
        output_str = re.sub(r":+", ":", output_str)

        # Remove all non-digits at the beginning and end of string, except for '+' or '-' for timezone
        output_str = re.sub(r"^[^\d+-]+|[^\d+-]+$", "", output_str)

        # Remove trailing dot if no microseconds
        output_str = re.sub(r"\.$", "", output_str)

        # Remove trailing colon or dash
        output_str = re.sub(r"[-:]\s*$", "", output_str)
        return output_str

    def to_str(self, output_format: Optional[str] = None) -> str:
        output_format = output_format or self._output_format
        if output_format == OutputFormat.datetime:
            return str(self.dt)
        elif output_format == OutputFormat.minimal_datetime:
            return self.to_minimal_datetime()
        elif output_format == OutputFormat.components:
            return str(self.to_components())
        return str(self.to_flex())

    def to_json(self, output_format: Optional[str] = None) -> str:
        return self.to_str(output_format)

    def __json__(self) -> str:
        return self.to_json()

    @classmethod
    def from_json(cls, json_str: str) -> "flextime":
        return flextime(json.loads(json_str))

    def to_components(self, output_fmt: Optional[str] = None) -> dict[str, int]:
        component_json = {
            "year": self.dt.year,
            "month": self.dt.month,
            "day": self.dt.day,
            "hour": self.dt.hour,
            "minute": self.dt.minute,
            "second": self.dt.second,
            "millisecond": self.dt.microsecond // 1000,
        }
        return {k: v for k, v in component_json.items() if not self.mask.get(k, False)}

    @property
    def mask_str(self) -> str:
        return self.mask_to_binary(self.mask)

    def to_flex(self) -> dict[str, str]:
        mask = self.mask_to_binary(self.mask)
        return {"dt": str(self.dt), "mask": mask}

    def to_datetime(self) -> datetime:
        return self.dt.datetime

    def __str__(self) -> str:
        """
        Returns the string representation of the datetime, considering the mask.
        """
        return self.to_str()

    def __repr__(self) -> str:
        return str(self)

    def get_comparable_dt(self) -> arrow.Arrow:
        """
        Creates a comparable datetime that respects the mask.
        """
        return arrow.get(
            self.dt.year if not self.mask["year"] else 1,
            self.dt.month if not self.mask["month"] else 1,
            self.dt.day if not self.mask["day"] else 1,
            self.dt.hour if not self.mask["hour"] else 0,
            self.dt.minute if not self.mask["minute"] else 0,
            self.dt.second if not self.mask["second"] else 0,
        )

    def _ensure_same_mask(self, other: "flextime") -> None:
        """
        Ensures that the mask of the current instance matches the mask of the other instance.
        """
        if self.mask != other.mask:
            raise ValueError(
                f"Cannot compare flextime instances with different masks. {self.mask} != {other.mask}"
            )

    def eq(self, other: "flextime", allow_different_masks: bool = False) -> bool:
        """
        Checks if the current instance is equal to the other instance.
        """
        if not isinstance(other, flextime):
            return False
        if not allow_different_masks:
            self._ensure_same_mask(other)
        return self.get_comparable_dt() == other.get_comparable_dt()

    def __eq__(self, other) -> bool:
        if not isinstance(other, flextime):
            return False
        self._ensure_same_mask(other)
        return self.get_comparable_dt() == other.get_comparable_dt()

    def __lt__(self, other) -> bool:
        if not isinstance(other, flextime):
            return NotImplemented
        self._ensure_same_mask(other)
        return self.get_comparable_dt() < other.get_comparable_dt()

    def __le__(self, other) -> bool:
        if not isinstance(other, flextime):
            return NotImplemented
        self._ensure_same_mask(other)
        return self.get_comparable_dt() <= other.get_comparable_dt()

    def __gt__(self, other) -> bool:
        if not isinstance(other, flextime):
            return NotImplemented
        self._ensure_same_mask(other)
        return self.get_comparable_dt() > other.get_comparable_dt()

    def __ge__(self, other) -> bool:
        if not isinstance(other, flextime):
            return NotImplemented
        self._ensure_same_mask(other)
        return self.get_comparable_dt() >= other.get_comparable_dt()

    @classmethod
    def __get_validators__(cls):
        yield cls.validate


try:
    import beanie
    import beanie.odm.utils.encoder as encoder

    def flextime_encoder(value: flextime) -> str:
        return value.to_json()

    encoder.DEFAULT_CUSTOM_ENCODERS[flextime] = flextime_encoder
except ImportError:
    pass
