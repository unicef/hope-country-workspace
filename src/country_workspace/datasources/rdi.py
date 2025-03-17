import io

from django.db.transaction import atomic
from hope_smart_import.readers import open_xls_multi

from country_workspace.models import AsyncJob, Batch, Household
from country_workspace.utils.fields import clean_field_name

RDI = str | io.BytesIO


def import_from_rdi(job: AsyncJob) -> dict[str, int]:
    ret = {"household": 0, "individual": 0}
    hh_ids = {}
    with atomic():
        batch_name = job.config["batch_name"]
        household_pk_col = job.config["household_pk_col"]
        master_column_label = job.config["master_column_label"]
        detail_column_label = job.config["detail_column_label"]
        rdi = job.file
        batch = Batch.objects.create(
            name=batch_name,
            program=job.program,
            country_office=job.program.country_office,
            imported_by=job.owner,
            source=Batch.BatchSource.RDI,
        )
        for sheet_index, sheet_generator in open_xls_multi(rdi, sheets=[0, 1]):
            for line, raw_record in enumerate(sheet_generator, 1):
                record = {}
                for k, v in raw_record.items():
                    record[clean_field_name(k)] = v
                if record[household_pk_col]:
                    try:
                        if sheet_index == 0:
                            hh: "Household" = job.program.households.create(
                                batch=batch,
                                name=raw_record[master_column_label],
                                flex_fields=record,
                            )
                            hh_ids[record[household_pk_col]] = hh.pk
                            ret["household"] += 1
                        elif sheet_index == 1:
                            try:
                                name = record[detail_column_label]
                            except KeyError:
                                raise Exception(
                                    "Error in configuration. '%s' is not a valid column name" % detail_column_label,
                                )
                            job.program.individuals.create(
                                batch=batch,
                                name=name,
                                household_id=hh_ids[record[household_pk_col]],
                                flex_fields=record,
                            )
                            ret["individual"] += 1
                    except Exception as e:  # noqa: BLE001
                        raise Exception("Error processing sheet %s line %s: %s" % (1 + sheet_index, line, e))
        return ret
