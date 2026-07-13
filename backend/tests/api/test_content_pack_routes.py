from app.main import app


def test_content_pack_resource_routes_are_registered_with_exact_methods():
    routes = {(path, method.upper()) for path, operation in app.openapi()["paths"].items() for method in operation}
    expected = {
        ("/stories/{story_id}", "GET"),
        ("/stories/{story_id}/evidence", "GET"),
        ("/stories/{story_id}/revisions", "GET"),
        ("/stories/{story_id}/content-packs", "POST"),
        ("/content-packs", "GET"),
        ("/content-packs/{pack_id}", "GET"),
        ("/platform-variants/{variant_id}/revisions", "GET"),
        ("/platform-variants/{variant_id}/revisions", "POST"),
        ("/platform-variants/{variant_id}/regenerate", "POST"),
        ("/platform-variant-revisions/{revision_id}/approve", "POST"),
        ("/platform-variant-revisions/{revision_id}/reject", "POST"),
    }
    assert expected <= routes
