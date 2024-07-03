from typing import Any, AnyStr, Dict, List

import io
import keyword
import os
import re
from collections import OrderedDict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.models.constants import LOOKUP_SEP

from django_regex.exceptions import InvalidPattern
from django_regex.utils import Regex, RegexList

from hope_country_report.utils.media import resource_path


class IRegexList(RegexList):
    def _compile(self, pattern: "str|re.Pattern", index: "int|None" = None) -> re.Pattern[AnyStr]:
        try:
            if isinstance(pattern, Regex):
                return pattern
            return re.compile(pattern, re.IGNORECASE)
        except (TypeError, re.error):
            raise InvalidPattern(pattern)


WANTED_TABLES = IRegexList(
    [
        "core.*",
        "household.*",
        "program.*",
        "geo.*",
        "payment.*",
        "targeting.*",
        "registration_data.*",
        "grievance.*",
    ]
)

IGNORED_TABLES = RegexList(
    [
        # "Activitylog.*",
        # "Advanced_filters.*",
        # "alembic_.*",
        # "api.*",
        # "Celery_.*",
        # "Chart",
        # "Connection",
        "core_filetemp",
        "core_flex.*",
        "core_migration.*",
        "core_storagefile",
        "core_xlsxkobotemplate",
        "household_xlsxupdatefile",
        # "CoreDatacollectingtypeCompatibleTypes",
        # "CoreFiletemp",
        # "CoreFlex.*",
        # "CoreMigrationstatus.*",
        # "CoreStoragefile",
        # "CoreXlsxkobotemplate",
        # "Dag.*",
        # "Depot.*",
        # "Django_.*",
        # "djcelery_.*",
        # "explorer_.*",
        # "flags_.*",
        # "import_export_.*",
        # "known_.*",
        # "kube_.*",
        # "serialized_dag",
        # "sla_miss",
        # "slot_pool",
        # "social_auth_.*",
        # "task_.*",
        # "users",
        # "variable",
        # "xcom",
        # "filer_.*",
        # "registration_emailregistrationprofile.*",
        # "reversion_.*",
        # "snapshotactivity"
        # "users_equitrackregistration.*",
        # "waffle_.*",
        # Tenant
    ]
)

MODEL_RENAME = {
    "Bankaccountinfo": "BankaccountInfo",
    "Businessarea": "BusinessArea",
    "Datacollectingtype": "DataCollectingType",
    "Documenttype": "DocumentType",
    "Documentvalidator": "DocumentValidator",
    "Entitlementcard": "EntitlementCard",
    "Paymentplan": "PaymentPlan",
    "Paymentrecord": "PaymentRecord",
    "Programcycle": "ProgramCycle",
    "Targetpopulation": "TargetPoulation",
    "Serviceprovider": "ServiceProvider",
}


def ignore_table(table_name: str):
    if table_name in IGNORED_TABLES:
        return True
    if table_name not in WANTED_TABLES:
        return True
    return False


class Command(BaseCommand):
    help = "Introspects the database tables in the given database/schema and outputs a Django model module."
    requires_system_checks = []
    requires_migrations_checks = False
    stealth_options = ("table_name_filter",)
    db_module = "etools_datamart.apps.multitenant"

    def add_arguments(self, parser):
        parser.add_argument(
            "table",
            action="store",
            nargs="*",
            type=str,
            help="Selects what tables or views should be introspected.",
        )
        parser.add_argument(
            "--database",
            action="store",
            dest="database",
            default="hope_ro",
            help='Nominates a database to introspect. Defaults to using the "default" database.',
        )
        parser.add_argument(
            "--schema",
            action="store",
            dest="schema",
            default="public",
            help='Nominates a schema to introspect. Defaults to using the "public" schema.',
        )
        parser.add_argument(
            "--output-file",
            action="store",
            default="_inspect.py",
            type=str,
            help="---",
        )

    def handle(self, **options: "Dict[Any]"):
        try:
            output_file = options["output_file"]
            buffer = io.StringIO()

            for line in self.handle_inspection(options):
                buffer.write("%s\n" % line)

            output_filepath = resource_path(f"apps/hope/models/{output_file}")
            Path(output_filepath).write_text(buffer.getvalue())
            os.system(f"black {output_filepath}")

        except NotImplementedError:
            raise CommandError("Database inspection isn't supported for the currently selected database backend.")

    def handle_inspection(self, options):  # noqa
        connection = connections[options["database"]]
        schema = options["schema"]

        def table2model(table_name):
            ret = table_name.title()
            if "_" in table_name:
                parts = [t.title() for t in table_name.split("_", 1)[1:]]
                ret = "".join(parts)
            else:
                ret = table_name.title()
            if ret in MODEL_RENAME:
                ret = MODEL_RENAME[ret]
            return re.sub(r"[^a-zA-Z0-9]", "", ret)

        def strip_prefix(s):
            return s[1:] if s.startswith("u'") else s

        # connection.mode = SINGLE_TENANT
        # state.schemas = [schema, "public"]
        connection.schema_name = schema
        # from etools_datamart.apps.sources.etools.enrichment import names
        with connection.cursor() as cursor:
            # cursor.execute(raw_sql(f"SET search_path={schema}"))
            yield "# flake8: noqa F405."
            yield "# This is an auto-generated Django model module."
            yield "# You'll have to do the following manually to clean this up:"
            yield "#   * Rearrange models' order"
            yield "#   * Make sure each model has one field with primary_key=True"
            yield "#   * Make sure each ForeignKey has `on_delete` set to the desired behavior."
            yield "# DO NOT rename the models, AND don't rename db_table values or field names."
            # yield "from django.db import models"
            yield "import django.contrib.postgres.fields"
            yield "from django.contrib.gis.db import models"

            yield "from hope_country_report.apps.hope.models._base import HopeModel"
            yield "from hope_country_report.apps.power_query.storage import HopeStorage"
            basemodel = "HopeModel"

            known_models = []
            tables_to_introspect = options["table"] or connection.introspection.table_names(cursor)

            for table_name in tables_to_introspect:
                if ignore_table(table_name):
                    continue
                known_fields: Dict[str, Dict[str:Any]] = {}
                model_name = table2model(table_name)
                try:
                    try:
                        relations = connection.introspection.get_relations(cursor, table_name)
                    except NotImplementedError:
                        relations = {}
                    try:
                        constraints = connection.introspection.get_constraints(cursor, table_name)
                    except NotImplementedError:
                        constraints = {}
                    primary_key_column = connection.introspection.get_primary_key_column(cursor, table_name)
                    unique_columns = [
                        c["columns"][0] for c in constraints.values() if c["unique"] and len(c["columns"]) == 1
                    ]
                    table_description = connection.introspection.get_table_description(cursor, table_name)
                except BaseException as e:
                    yield "# Unable to inspect table '%s'" % table_name
                    yield "# The error was: %s" % e
                    continue

                yield ""
                yield ""
                yield "class %s(%s):" % (model_name, basemodel)

                known_models.append(model_name)
                used_column_names = []  # Holds column names used in the table so far
                column_to_field_name = {}  # Maps column names to names of model fields
                for index, row in enumerate(table_description):
                    comment_notes = []  # Holds Field notes, to be displayed in a Python comment.
                    extra_params = OrderedDict()  # Holds Field parameters such as 'db_column'.
                    column_name = row[0]
                    is_relation = column_name in relations

                    att_name, params, notes = self.normalize_col_name(column_name, used_column_names, is_relation)
                    extra_params.update(params)
                    comment_notes.extend(notes)

                    used_column_names.append(att_name)
                    column_to_field_name[column_name] = att_name

                    # Add primary_key and unique, if necessary.
                    if column_name == primary_key_column:
                        extra_params["primary_key"] = True
                    elif column_name in unique_columns:
                        extra_params["unique"] = True

                    if is_relation:
                        rel_to = (
                            "self"
                            if relations[column_name][1] == table_name
                            else table2model(relations[column_name][1])
                        )

                        if "unique" in extra_params:
                            extra_params.pop("unique")
                            ftype = "OneToOneField"
                        elif "primary_key" in extra_params:
                            extra_params.pop("primary_key")
                            ftype = "OneToOneField"
                        else:
                            ftype = "ForeignKey"
                        # skip fields to unwanted models
                        # if relations[column_name][1] not in WANTED_TABLES:
                        #     print("111: 262", relations[column_name][1])
                        # else:
                        #     print("222: 262", relations[column_name][1])
                        if ignore_table(relations[column_name][1]):
                            continue

                        if rel_to in known_models:
                            field_type = f"{ftype}({rel_to}"
                        else:
                            field_type = f"{ftype}('{rel_to}'"

                    else:
                        # Calling `get_field_type` to get the field type string and any
                        # additional parameters and notes.
                        field_type, field_params, field_notes = self.get_field_type(connection, table_name, row)
                        extra_params.update(field_params)
                        comment_notes.extend(field_notes)

                        field_type += "("
                    # Don't output 'id = meta.AutoField(primary_key=True)', because
                    # that's assumed if it doesn't exist.
                    if field_type == "AutoField(":
                        continue
                    if att_name == "id" and extra_params == {"primary_key": True}:
                        if field_type == "AutoField(":
                            continue
                        elif field_type == "IntegerField(" and not connection.features.introspected_field_types:
                            comment_notes.append("AutoField?")

                    # Add 'null' and 'blank', if the 'null_ok' flag was present in the
                    # table description.
                    if row[6]:  # If it's NULL...
                        extra_params["blank"] = True
                        extra_params["null"] = True

                    if not extra_params.get("primary_key", None):
                        extra_params["null"] = True
                    known_fields[att_name] = {"field_type": field_type, "extra_params": extra_params}

                    field_desc = "%s = %s%s" % (
                        att_name,
                        # Custom fields will have a dotted path
                        "" if "." in field_type else "models.",
                        field_type,
                    )
                    if field_type.startswith("ForeignKey(") or field_type.startswith("OneToOneField("):
                        # _related_name = f'{table2model(relations[column_name][1]).lower()}_{table_name}_{column_name}'
                        _related_name = f"{model_name}.{att_name}".lower()

                        _related_name = _related_name.replace(".", "_")
                        field_desc += ", on_delete=models.DO_NOTHING"
                        field_desc += f", related_name='{_related_name}'"

                    if field_type.startswith("ImageField("):
                        field_desc += "storage=HopeStorage()"

                    if extra_params:
                        if not field_desc.endswith("("):
                            field_desc += ", "
                        field_desc += ", ".join("%s=%s" % (k, strip_prefix(repr(v))) for k, v in extra_params.items())
                    field_desc += ")"
                    if comment_notes:
                        field_desc += "  # " + " ".join(comment_notes)
                    yield "    %s" % field_desc
                for meta_line in self.get_meta(table_name, constraints, column_to_field_name):
                    yield meta_line

                yield ""
                yield "    class Tenant:"
                yield '        tenant_filter_field: str = "__all__"'
                for attr in ["name", "username", "code", "description"]:
                    if attr in known_fields:
                        yield "    def __str__(self) -> str:"
                        yield f"        return str(self.{attr})"
                        break

    def normalize_col_name(self, col_name: str, used_column_names: List[str], is_relation: bool):  # noqa
        """
        Modify the column name to make it Python-compatible as a field name
        """
        field_params = {}
        field_notes = []

        new_name = col_name.lower()
        if new_name != col_name:
            field_notes.append("Field name made lowercase.")

        if is_relation:
            if new_name.endswith("_id"):
                new_name = new_name[:-3]
            else:
                field_params["db_column"] = col_name

        new_name, num_repl = re.subn(r"\W", "_", new_name)
        if num_repl > 0:
            field_notes.append("Field renamed to remove unsuitable characters.")

        if new_name.find(LOOKUP_SEP) >= 0:
            while new_name.find(LOOKUP_SEP) >= 0:
                new_name = new_name.replace(LOOKUP_SEP, "_")
            if col_name.lower().find(LOOKUP_SEP) >= 0:
                # Only add the comment if the double underscore was in the original name
                field_notes.append("Field renamed because it contained more than one '_' in a row.")

        if new_name.startswith("_"):
            new_name = "field%s" % new_name
            field_notes.append("Field renamed because it started with '_'.")

        if new_name.endswith("_"):
            new_name = "%sfield" % new_name
            field_notes.append("Field renamed because it ended with '_'.")

        if keyword.iskeyword(new_name):
            new_name += "_field"
            field_notes.append("Field renamed because it was a Python reserved word.")

        if new_name[0].isdigit():
            new_name = "number_%s" % new_name
            field_notes.append("Field renamed because it wasn't a valid Python identifier.")

        if new_name in used_column_names:
            num = 0
            while "%s_%d" % (new_name, num) in used_column_names:
                num += 1
            new_name = "%s_%d" % (new_name, num)
            field_notes.append("Field renamed because of name conflict.")

        if col_name != new_name and field_notes:
            field_params["db_column"] = col_name

        return new_name, field_params, field_notes

    def get_field_type(self, connection: Any, table_name: str, row: List):
        """
        Given the database connection, the table name, and the cursor row
        description, this routine will return the given field type name, as
        well as any additional keyword parameters and notes for the field.
        """
        field_params = OrderedDict()
        field_notes = []

        try:
            field_type = connection.introspection.get_field_type(row[1], row)
        except KeyError:
            field_type = "TextField"
            field_notes.append("This field type is a guess.")

        # This is a hook for data_types_reverse to return a tuple of
        # (field_type, field_params_dict).
        if type(field_type) is tuple:
            field_type, new_params = field_type
            field_params.update(new_params)

        # Add max_length for all CharFields.
        if field_type == "CharField" and row[3]:
            field_params["max_length"] = int(row[3])

        if field_type == "DecimalField":
            if row[4] is None or row[5] is None:
                field_notes.append(
                    "max_digits and decimal_places have been guessed, as this "
                    "database handles decimal fields as float"
                )
                field_params["max_digits"] = row[4] if row[4] is not None else 10
                field_params["decimal_places"] = row[5] if row[5] is not None else 5
            else:
                field_params["max_digits"] = row[4]
                field_params["decimal_places"] = row[5]

        image_fields = {
            "household_household": [
                "consent_sign",
            ],
            "household_document": [
                "photo",
            ],
            "household_individual": ["photo", "disability_certificate_picture"],
        }
        if row[0] in image_fields.get(table_name, []):
            field_type = "ImageField"
            field_params.pop("max_length", None)

        return field_type, field_params, field_notes

    def get_meta(self, table_name: str, constraints: Any, column_to_field_name: Dict[str, Any]) -> List[str]:
        """
        Return a sequence comprising the lines of code necessary
        to construct the inner Meta class for the model corresponding
        to the given database table name.
        """
        unique_together = set()
        for index, params in constraints.items():
            if params["unique"]:
                columns = params["columns"]
                if len(columns) > 1:
                    cols = set(columns)
                    # we do not want to include the u"" or u'' prefix
                    # so we build the string rather than interpolate the tuple
                    fields = [column_to_field_name[c] for c in cols if len(cols) > 1]
                    if fields:
                        tup = (
                            "("
                            + ", ".join(sorted(["'%s'" % column_to_field_name[c] for c in cols if len(cols) > 1]))
                            + ")"
                        )
                        unique_together.add(tup)
        meta = ["", "    class Meta:", "        managed = False", "        db_table = '%s'" % table_name]

        # if unique_together:
        #     tup = "(" + ", ".join(sorted(unique_together)) + ",)"
        #     meta += ["        unique_together = %s" % tup]
        return meta
