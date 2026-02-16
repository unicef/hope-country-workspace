from typing import Any

from country_workspace.contrib.dedup import DeduplicationClient
from country_workspace.models import AsyncJob, Batch, Individual

IMAGE_FIELD_CANDIDATES = ("photo", "national_id_photo", "national_passport_photo")


def _get_image_reference(individual: Individual) -> str | None:
    for source in (individual.flex_fields, individual.raw_data):
        for field_name in IMAGE_FIELD_CANDIDATES:
            value = source.get(field_name)
            if isinstance(value, str) and value.strip() and not value.startswith("data:"):
                return value.strip()
    return None


def trigger_batch_deduplication(job: AsyncJob) -> dict[str, Any]:
    batch_id = job.config.get("batch_id")
    if not batch_id:
        raise ValueError("batch_id is required in job config")

    batch = Batch.objects.select_related("program", "country_office").get(pk=batch_id)
    queryset = batch.individual_set.filter(removed=False).only("id", "flex_fields", "raw_data")

    images = []
    skipped_without_image = 0
    for individual in queryset:
        if image_reference := _get_image_reference(individual):
            images.append({"reference_pk": str(individual.pk), "filename": image_reference})
        else:
            skipped_without_image += 1

    dedup_reference_pk = f"cw-batch-{batch.pk}"
    if not images:
        return {
            "batch_id": batch.pk,
            "batch_name": batch.name,
            "dedup_reference_pk": dedup_reference_pk,
            "total_records": queryset.count(),
            "images_pushed": 0,
            "skipped_without_image": skipped_without_image,
            "status": "skipped_no_images",
        }

    client = DeduplicationClient()
    client.upsert_deduplication_set(
        reference_pk=dedup_reference_pk,
        name=batch.name or dedup_reference_pk,
        settings={
            "source": "country_workspace",
            "batch_id": batch.pk,
            "program_id": batch.program_id,
            "country_office_id": batch.country_office_id,
        },
    )
    client.bulk_add_images(dedup_reference_pk, images)
    process_result = client.process(dedup_reference_pk)

    return {
        "batch_id": batch.pk,
        "batch_name": batch.name,
        "dedup_reference_pk": dedup_reference_pk,
        "total_records": queryset.count(),
        "images_pushed": len(images),
        "skipped_without_image": skipped_without_image,
        "status": "triggered",
        "process_message": process_result.get("message", ""),
    }
