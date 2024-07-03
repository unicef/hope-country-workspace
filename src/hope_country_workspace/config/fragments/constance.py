CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"

CONSTANCE_CONFIG = {
    "NEW_USER_IS_STAFF": (False, "Set any new user as staff", bool),
    "NEW_USER_DEFAULT_GROUP": (
        "Default",
        "Group to assign to any new user",
        str,
    ),
    "BLOB_FROM_IMAGE_SCALE_FACTOR": (
        1.0,
        """Specifies the scaling factor applied to all pixel values when converting an image to a blob. Mostly
        it equals 1.0 for no scaling or 1.0/255.0 and normalizing to the [0, 1] range.
        Remember that scaling factor is also applied to mean values. Both scaling factor and mean values
        must be the same for the training and inference to get the correct results.
        """,
        float,
    ),
    "BLOB_FROM_IMAGE_MEAN_VALUES": (
        "104.0, 177.0, 123.0",
        """Specifies the mean BGR values used in image preprocessing to normalize pixel values by subtracting
        the mean values of the training dataset. This helps in reducing model bias and improving accuracy.
        The specified mean values are subtracted from each channel (Blue, Green, Red) of the input image.
        Remember that mean values are also applied to scaling factor. Both scaling factor and mean values
        must be the same for the training and inference to get the correct results.
        """,
        "tuple_field",
    ),
    "FACE_DETECTION_CONFIDENCE": (
        0.7,
        """
        Specifies the minimum confidence score required for a detected face to be considered valid. Detections
        with confidence scores below this threshold are discarded as likely false positives.
        """,
        float,
    ),
    "NMS_THRESHOLD": (
        0.4,
        """
        Specifies the Intersection over Union (IoU) threshold used in Non-Maximum Suppression (NMS) to filter out
        overlapping bounding boxes. If the IoU between two boxes exceeds this threshold, the box with the lower
        confidence score is suppressed. Lower values result in fewer, more distinct boxes; higher values allow more
        overlapping boxes to remain.
        """,
        float,
    ),
    "FACE_ENCODINGS_NUM_JITTERS": (
        1,
        """
        Specifies the number of times to re-sample the face when calculating the encoding. Higher values increase
        accuracy but are computationally more expensive and slower. For example, setting 'num_jitters' to 100 makes
        the process 100 times slower.
        """,
        int,
    ),
    "FACE_ENCODINGS_MODEL": (
        "small",
        """
        Specifies the model type used for encoding face landmarks. It can be either 'small' which is faster and
        detects only 5 key facial landmarks, or 'large' which is more precise and identifies 68 key facial landmarks
        but requires more computational resources.
        """,
        "face_encodings_model",
    ),
    "FACE_DISTANCE_THRESHOLD": (
        0.5,
        """
        Specifies the maximum allowable distance between two face embeddings for them to be considered a match. It helps
        determine if two faces belong to the same person by setting a threshold for similarity. Lower values result in
        stricter matching, while higher values allow for more lenient matches.
        """,
        float,
    ),
}


CONSTANCE_CONFIG_FIELDSETS = {
    "User settings": {
        "fields": ("NEW_USER_IS_STAFF", "NEW_USER_DEFAULT_GROUP"),
        "collapse": False,
    },
    "Face recognition settings": {
        "fields": (
            "DNN_BACKEND",
            "DNN_TARGET",
            "BLOB_FROM_IMAGE_SCALE_FACTOR",
            "BLOB_FROM_IMAGE_MEAN_VALUES",
            "FACE_DETECTION_CONFIDENCE",
            "NMS_THRESHOLD",
            "FACE_ENCODINGS_NUM_JITTERS",
            "FACE_ENCODINGS_MODEL",
            "FACE_DISTANCE_THRESHOLD",
        ),
        "collapse": False,
    },
}

CONSTANCE_ADDITIONAL_FIELDS = {
    "email": [
        "django.forms.EmailField",
        {},
    ],
}
