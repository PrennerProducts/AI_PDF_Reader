from main import _postprocess_image_rows


def test_alu_one_repeated_header_logo_is_filtered() -> None:
    logo_row = {
        "page_ref": 1,
        "image_index": 1,
        "mime_type": "image/png",
        "storage_path": "/tmp/logo.png",
        "sha256": "x",
        "width": 230,
        "height": 109,
        "bytes_size": 9632,
        "metadata_json": {
            "layout_source": "fitz_image_block",
            "top_ratio": 0.020452,
            "left_ratio": 0.070588,
            "width_ratio": 0.29,
            "height_ratio": 0.097206,
        },
    }
    drawing_row = {
        "page_ref": 1,
        "image_index": 2,
        "mime_type": "image/png",
        "storage_path": "/tmp/drawing.png",
        "sha256": "y",
        "width": 558,
        "height": 900,
        "bytes_size": 13519,
        "metadata_json": {
            "layout_source": "fitz_image_block",
            "top_ratio": 0.45434,
            "left_ratio": 0.272269,
            "width_ratio": 0.23521,
            "height_ratio": 0.269382,
        },
    }

    rows = [
        {**logo_row, "page_ref": 1},
        {**logo_row, "page_ref": 2},
        {**logo_row, "page_ref": 3},
        drawing_row,
    ]

    filtered = _postprocess_image_rows(
        rows,
        template="alu_one",
        document_type="angebot",
        extracted_text="",
    )

    assert filtered == [drawing_row]


def test_alu_one_first_page_header_logo_variant_is_filtered() -> None:
    logo_row = {
        "page_ref": 1,
        "image_index": 1,
        "mime_type": "image/png",
        "storage_path": "/tmp/logo.png",
        "sha256": "x",
        "width": 230,
        "height": 109,
        "bytes_size": 9632,
        "metadata_json": {
            "layout_source": "fitz_image_block",
            "top_ratio": 0.041855,
            "left_ratio": 0.070588,
            "width_ratio": 0.29,
            "height_ratio": 0.097206,
        },
    }
    drawing_row = {
        "page_ref": 1,
        "image_index": 2,
        "mime_type": "image/png",
        "storage_path": "/tmp/drawing.png",
        "sha256": "y",
        "width": 558,
        "height": 900,
        "bytes_size": 13519,
        "metadata_json": {
            "layout_source": "fitz_image_block",
            "top_ratio": 0.45434,
            "left_ratio": 0.272269,
            "width_ratio": 0.23521,
            "height_ratio": 0.269382,
        },
    }

    filtered = _postprocess_image_rows(
        [logo_row, drawing_row],
        template="alu_one",
        document_type="angebot",
        extracted_text="",
    )

    assert filtered == [drawing_row]
