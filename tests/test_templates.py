from fastapi import Request

from app.main import KIND_NAMES, app, templates


def test_teacher_documents_show_student_opening_not_teacher_access():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard",
            "root_path": "",
            "scheme": "http",
            "server": ("localhost", 8000),
            "headers": [],
            "query_string": b"",
            "router": app.router,
        }
    )
    materials = [
        {
            "id": kind,
            "kind": name,
            "kind_id": kind,
            "title": f"Material {kind}",
            "created_at": 0,
            "has_prev": False,
            "accessible": True,
            "unlocks_at": 86400 if kind in (2, 3) else 0,
        }
        for kind, name in enumerate(KIND_NAMES)
    ]
    response = templates.TemplateResponse(
        request=request,
        name="teacher.html",
        context={
            "user": {"username": "teacher", "role": "teacher"},
            "materials": materials,
            "pending": [],
            "students": [],
            "kinds": list(enumerate(KIND_NAMES)),
            "messages": [],
            "csrf_token": "test-token",
        },
    )
    html = response.body.decode()
    assert "Ouverture aux inscrits" in html
    assert html.count(templates.env.filters["dt"](86400)) == 2
    assert html.count("dès inscription") == 2
    assert ">ouvert</span>" not in html
    for material in materials:
        assert f'/material/{material["id"]}/download' in html