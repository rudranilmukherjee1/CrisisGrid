import os
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from clear_incidents import clear_incidents

from models.incident import Incident
from models.resource import Resource

from schemas import (
    EmergencyReport,
    IncidentDescriptionUpdate,
    ResourceCreate,
    ResourceStatusUpdate,
    ResourceLocationUpdate,
    DispatchAssignmentRequest,
)

from ai_extractor import extract_incident_data

from incident_repository import (
    create_incident,
    get_incident,
    get_all_incidents,
    update_incident_from_ai,
)

from resource_repository import (
    create_resource,
    get_resource,
    get_all_resources,
    update_resource_status,
    update_resource_location,
)

from assignment_repository import (
    assign_resources_to_incident,
    get_incident_assignments,
    start_incident_response,
    resolve_incident_response,
)

from priority_engine import calculate_priority

from resource_matcher import match_resources

from dispatch_engine import build_dispatch_plan

# ===================================================
# FRONTEND
# ===================================================

from frontend import router as frontend_router





app = FastAPI(title="CrisisGrid API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows requests from Vercel
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------
# CONNECT FRONTEND ROUTES
# ---------------------------------------------------

app.include_router(
    frontend_router
)


# ---------------------------------------------------
# INITIALIZE DATABASE
# ---------------------------------------------------

init_db()


# ===================================================
# HOME
# ===================================================

@app.get("/")
def home():

    return {
        "message": "CrisisGrid backend is running",
        "version": "1.1.0",
        "dashboard": "/dashboard",
    }


# ===================================================
# INCIDENT MANAGEMENT
# ===================================================


# ---------------------------------------------------
# CREATE INCIDENT
# ---------------------------------------------------

@app.post(
    "/incidents",
    status_code=201
)
def report_incident(
    data: EmergencyReport
):

    # ===============================================
    # AI EXTRACTION
    # ===============================================

    try:

        extracted = extract_incident_data(
            data.description
        )

    except Exception as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "AI extraction failed: "
                f"{str(error)}"
            ),
        )


    # ===============================================
    # CREATE INCIDENT
    # ===============================================

    incident = Incident(

        description=data.description,

        location=data.location,

        latitude=data.latitude,

        longitude=data.longitude,

        disaster_type=(
            extracted.disaster_type
        ),

        people_affected=(
            extracted.people_affected
        ),

        vulnerable_people=(
            extracted.vulnerable_people
        ),

        injuries=(
            extracted.injuries
        ),

        mobility_issue=(
            extracted.mobility_issue
        ),

        danger_level=0,

        required_resources=(
            extracted.required_resources
        ),
    )


    saved_incident = create_incident(
        incident
    )


    priority = calculate_priority(
        saved_incident
    )


    return {

        "incident":
            saved_incident,

        "ai_extraction":
            extracted.model_dump(),

        "priority":
            priority,
    }


# ---------------------------------------------------
# GET ALL INCIDENTS
# ---------------------------------------------------

@app.get("/incidents")
def list_incidents():

    incidents = get_all_incidents()

    result = []


    for incident in incidents:

        priority = calculate_priority(
            incident
        )


        result.append(
            {
                "incident":
                    incident,

                "priority":
                    priority,
            }
        )


    # Highest priority incidents first
    result.sort(
        key=lambda item:
            item["priority"]["score"],
        reverse=True,
    )


    return result

# ---------------------------------------------------
# ADMIN: CLEAR ALL INCIDENTS
# ---------------------------------------------------

@app.delete("/admin/incidents")
def clear_all_incidents(
    x_admin_token: str = Header(
        ...,
        alias="X-Admin-Token"
    )
):

    # ===============================================
    # CHECK ADMIN TOKEN
    # ===============================================

    expected_token = os.getenv(
        "ADMIN_CLEANUP_TOKEN"
    )


    if not expected_token:

        raise HTTPException(
            status_code=500,
            detail=(
                "ADMIN_CLEANUP_TOKEN "
                "is not configured"
            ),
        )


    if x_admin_token != expected_token:

        raise HTTPException(
            status_code=403,
            detail="Invalid admin token",
        )


    # ===============================================
    # CLEAR INCIDENTS
    # ===============================================

    try:

        clear_incidents()

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=(
                "Incident cleanup failed: "
                f"{str(error)}"
            ),
        )


    # ===============================================
    # VERIFY CLEANUP
    # ===============================================

    remaining_incidents = (
        get_all_incidents()
    )


    if remaining_incidents:

        raise HTTPException(
            status_code=500,
            detail=(
                "Cleanup failed. "
                f"{len(remaining_incidents)} "
                "incidents remain."
            ),
        )


    # ===============================================
    # SUCCESS
    # ===============================================

    return {

        "message":
            "All incidents cleared successfully",

        "remaining_incidents":
            0,
    }


# ---------------------------------------------------
# GET ONE INCIDENT
# ---------------------------------------------------

@app.get(
    "/incidents/{incident_id}"
)
def fetch_incident(
    incident_id: str
):

    incident = get_incident(
        incident_id
    )


    if incident is None:

        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )


    return {

        "incident":
            incident,

        "priority":
            calculate_priority(
                incident
            ),
    }


# ---------------------------------------------------
# UPDATE INCIDENT DESCRIPTION
# ---------------------------------------------------

@app.patch(
    "/incidents/{incident_id}/description"
)
def update_description(
    incident_id: str,
    data: IncidentDescriptionUpdate,
):

    old_incident = get_incident(
        incident_id
    )


    if old_incident is None:

        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )


    # ===============================================
    # NORMALIZE TEXT
    # ===============================================

    old_text = " ".join(
        old_incident[
            "description"
        ]
        .lower()
        .split()
    )


    new_text = " ".join(
        data.description
        .lower()
        .split()
    )


    # ===============================================
    # DUPLICATE UPDATE CHECK
    # ===============================================

    if old_text == new_text:

        current_priority = (
            calculate_priority(
                old_incident
            )
        )


        return {

            "message": (
                "This update is identical "
                "to the current incident "
                "description."
            ),

            "incident":
                old_incident,

            "priority_change": {

                "before":
                    current_priority,

                "after":
                    current_priority,

                "score_change":
                    0,
            },
        }


    # ===============================================
    # PRIORITY BEFORE UPDATE
    # ===============================================

    old_priority = calculate_priority(
        old_incident
    )


    # ===============================================
    # BUILD AI CONTEXT
    # ===============================================

    context_parts = []


    for previous_report in (
        old_incident["updates"]
    ):

        context_parts.append(
            "Previous report:\n"
            + previous_report
        )


    context_parts.append(
        "Current situation:\n"
        + old_incident[
            "description"
        ]
    )


    context_parts.append(
        "New update:\n"
        + data.description
    )


    combined_description = (
        "\n\n".join(
            context_parts
        )
    )


    # ===============================================
    # AI RE-EXTRACTION
    # ===============================================

    try:

        extracted = extract_incident_data(
            combined_description
        )

    except Exception as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "AI extraction failed: "
                f"{str(error)}"
            ),
        )


    # ===============================================
    # SAVE UPDATE
    # ===============================================

    updated_incident = (
        update_incident_from_ai(
            incident_id,
            data.description,
            extracted,
        )
    )


    # ===============================================
    # PRIORITY AFTER UPDATE
    # ===============================================

    new_priority = calculate_priority(
        updated_incident
    )


    score_change = round(
        new_priority["score"]
        -
        old_priority["score"],
        2,
    )


    return {

        "incident":
            updated_incident,

        "ai_extraction":
            extracted.model_dump(),

        "priority_change": {

            "before":
                old_priority,

            "after":
                new_priority,

            "score_change":
                score_change,
        },
    }


# ===================================================
# RESOURCE MATCHING
# ===================================================


@app.get(
    "/incidents/{incident_id}/resource-matches"
)
def find_resource_matches(
    incident_id: str
):

    incident = get_incident(
        incident_id
    )


    if incident is None:

        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )


    resources = get_all_resources()


    matches = match_resources(
        incident,
        resources,
    )


    return {

        "incident": {

            "incident_id":
                incident["incident_id"],

            "description":
                incident["description"],

            "location":
                incident["location"],

            "latitude":
                incident["latitude"],

            "longitude":
                incident["longitude"],

            "required_resources":
                incident[
                    "required_resources"
                ],

            "people_affected":
                incident[
                    "people_affected"
                ],

            "injuries":
                incident[
                    "injuries"
                ],
        },

        "priority":
            calculate_priority(
                incident
            ),

        "resource_matching":
            matches,
    }


# ===================================================
# DISPATCH RECOMMENDATION
# ===================================================


@app.get(
    "/incidents/{incident_id}/dispatch-recommendation"
)
def get_dispatch_recommendation(
    incident_id: str
):

    incident = get_incident(
        incident_id
    )


    if incident is None:

        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )


    # ===============================================
    # GPS REQUIRED FOR ROUTING
    # ===============================================

    if (
        incident["latitude"] is None
        or
        incident["longitude"] is None
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Incident does not have "
                "GPS coordinates."
            ),
        )


    resources = get_all_resources()


    # ===============================================
    # BUILD DISPATCH PLAN
    # ===============================================

    try:

        dispatch_plan = (
            build_dispatch_plan(
                incident,
                resources,
            )
        )

    except Exception as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "Dispatch calculation failed: "
                f"{str(error)}"
            ),
        )


    return {

        "incident": {

            "incident_id":
                incident[
                    "incident_id"
                ],

            "description":
                incident[
                    "description"
                ],

            "location":
                incident[
                    "location"
                ],

            "latitude":
                incident[
                    "latitude"
                ],

            "longitude":
                incident[
                    "longitude"
                ],

            "required_resources":
                incident[
                    "required_resources"
                ],
        },

        "priority":
            calculate_priority(
                incident
            ),

        "dispatch_plan":
            dispatch_plan,
    }


# ===================================================
# RESOURCE ASSIGNMENT
# ===================================================


# ---------------------------------------------------
# ASSIGN RESOURCES
# ---------------------------------------------------

@app.post(
    "/incidents/{incident_id}/assign"
)
def assign_incident_resources(
    incident_id: str,
    data: DispatchAssignmentRequest,
):

    incident = get_incident(
        incident_id
    )


    if incident is None:

        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )


    try:

        assignments = (
            assign_resources_to_incident(
                incident_id,
                data.resource_ids,
            )
        )


    except ValueError as error:

        raise HTTPException(
            status_code=400,
            detail=str(error),
        )


    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=(
                "Resource assignment failed: "
                f"{str(error)}"
            ),
        )


    updated_incident = get_incident(
        incident_id
    )


    return {

        "message":
            "Resources assigned successfully",

        "incident":
            updated_incident,

        "assignments":
            assignments,
    }


# ---------------------------------------------------
# GET ASSIGNED RESOURCES
# ---------------------------------------------------

@app.get(
    "/incidents/{incident_id}/assignments"
)
def fetch_incident_assignments(
    incident_id: str
):

    incident = get_incident(
        incident_id
    )


    if incident is None:

        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )


    assignments = (
        get_incident_assignments(
            incident_id
        )
    )


    return {

        "incident_id":
            incident_id,

        "status":
            incident["status"],

        "assignments":
            assignments,
    }


# ===================================================
# INCIDENT RESPONSE LIFECYCLE
# ===================================================


# ---------------------------------------------------
# START RESPONSE
# ---------------------------------------------------

@app.post(
    "/incidents/{incident_id}/start"
)
def start_response(
    incident_id: str
):

    incident = get_incident(
        incident_id
    )


    if incident is None:

        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )


    try:

        assignments = (
            start_incident_response(
                incident_id
            )
        )


    except ValueError as error:

        raise HTTPException(
            status_code=400,
            detail=str(error),
        )


    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not start response: "
                f"{str(error)}"
            ),
        )


    updated_incident = get_incident(
        incident_id
    )


    return {

        "message":
            "Emergency response started",

        "incident":
            updated_incident,

        "assignments":
            assignments,
    }


# ---------------------------------------------------
# RESOLVE INCIDENT
# ---------------------------------------------------

@app.post(
    "/incidents/{incident_id}/resolve"
)
def resolve_response(
    incident_id: str
):

    incident = get_incident(
        incident_id
    )


    if incident is None:

        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )


    try:

        assignments = (
            resolve_incident_response(
                incident_id
            )
        )


    except ValueError as error:

        raise HTTPException(
            status_code=400,
            detail=str(error),
        )


    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not resolve incident: "
                f"{str(error)}"
            ),
        )


    updated_incident = get_incident(
        incident_id
    )


    return {

        "message":
            "Incident resolved successfully",

        "incident":
            updated_incident,

        "assignments":
            assignments,
    }


# ===================================================
# RESOURCE MANAGEMENT
# ===================================================


# ---------------------------------------------------
# CREATE RESOURCE
# ---------------------------------------------------

@app.post(
    "/resources",
    status_code=201
)
def register_resource(
    data: ResourceCreate
):

    resource = Resource(

        name=data.name,

        resource_type=(
            data.resource_type
        ),

        capacity=data.capacity,

        capabilities=(
            data.capabilities
        ),

        equipment=(
            data.equipment
        ),

        location=data.location,

        latitude=data.latitude,

        longitude=data.longitude,
    )


    return create_resource(
        resource
    )


# ---------------------------------------------------
# GET ALL RESOURCES
# ---------------------------------------------------

@app.get("/resources")
def list_resources():

    return get_all_resources()


# ---------------------------------------------------
# GET ONE RESOURCE
# ---------------------------------------------------

@app.get(
    "/resources/{resource_id}"
)
def fetch_resource(
    resource_id: str
):

    resource = get_resource(
        resource_id
    )


    if resource is None:

        raise HTTPException(
            status_code=404,
            detail="Resource not found",
        )


    return resource


# ---------------------------------------------------
# UPDATE RESOURCE STATUS
# ---------------------------------------------------

@app.patch(
    "/resources/{resource_id}/status"
)
def change_resource_status(
    resource_id: str,
    data: ResourceStatusUpdate,
):

    allowed_statuses = {
        "available",
        "assigned",
        "busy",
        "offline",
    }


    new_status = (
        data.status
        .strip()
        .lower()
    )


    if new_status not in allowed_statuses:

        raise HTTPException(
            status_code=400,
            detail=(
                "Status must be one of: "
                "available, assigned, "
                "busy, offline"
            ),
        )


    resource = update_resource_status(
        resource_id,
        new_status,
    )


    if resource is None:

        raise HTTPException(
            status_code=404,
            detail="Resource not found",
        )


    return resource


# ---------------------------------------------------
# UPDATE LIVE RESOURCE LOCATION
# ---------------------------------------------------

@app.patch(
    "/resources/{resource_id}/location"
)
def change_resource_location(
    resource_id: str,
    data: ResourceLocationUpdate,
):

    resource = (
        update_resource_location(

            resource_id=resource_id,

            latitude=data.latitude,

            longitude=data.longitude,
        )
    )


    if resource is None:

        raise HTTPException(
            status_code=404,
            detail="Resource not found",
        )


    return {

        "message":
            "Resource location updated successfully",

        "resource":
            resource,
    }
