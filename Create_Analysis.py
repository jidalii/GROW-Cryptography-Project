import asyncio
import json
import os
import threading
import random

import streamlit as st
import pandas as pd

from dataclasses import dataclass
from itertools import chain
from multiprocessing.shared_memory import SharedMemory
from typing import Any

import sqlalchemy
from sqlalchemy import create_engine
import psycopg2

from streamlit_extras.stylable_container import stylable_container
from streamlit.components.v1 import html

from streamlit.web.server import Server
from streamlit.web.server.server import start_listening
from tornado.web import RequestHandler


st.set_page_config(
    page_title="QueryShield",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.title("QueryShield")
login = st.sidebar.button("Login")


@st.experimental_dialog("Login")
def email_form():
    with st.form("Login", border=False, clear_on_submit=True):
        name = st.text_input("Name", key="key1")
        email = st.text_input("Email", key="key2")
        if st.form_submit_button("Submit"):
            st.rerun()


if login:
    email_form()


if "disabled" not in st.session_state:
    st.session_state["disabled"] = False


def disable():
    st.session_state["disabled"] = True


def submit_btn():
    return st.button("Submit")


st.title("Create New Analysis")

_JS_TO_PD_COL_OFFSET: int = -2

# Create shared memory for the payload
try:
    payload_memory = SharedMemory(name="JS_PAYLOAD", create=True, size=128)
except FileExistsError:
    payload_memory = SharedMemory(name="JS_PAYLOAD", create=False, size=128)


@dataclass
class Selection:
    """Dataclass to store the selected cell information."""

    col: int
    row: int
    sorted_by: int


def sort_df_by_selected_col(table: pd.DataFrame, js_sorted_by: int) -> pd.DataFrame:
    if js_sorted_by == 1:
        return table
    elif js_sorted_by == -1:
        return table.sort_index(axis=0, ascending=False)
    sorting_col: str = table.columns[abs(js_sorted_by) + _JS_TO_PD_COL_OFFSET]
    return table.sort_values(by=sorting_col, ascending=js_sorted_by > 0)


def _retrieve_payload() -> Selection:
    """Retrieve the payload from the shared memory and return it as a tuple."""
    payload = {}
    if payload_memory.buf[0] != 0:
        payload_bytes = bytearray(payload_memory.buf[:])
        payload_str = payload_bytes.decode("utf-8").rstrip("\x00")
        payload_length, payload = len(payload_str), json.loads(payload_str)
        payload_memory.buf[:payload_length] = bytearray(payload_length)
    if payload:
        selected_cell_info = Selection(
            *(
                int(val)
                for val in chain(
                    payload.get("cellId").split(","), [payload.get("sortedByCol")]
                )
            )
        )
        print(
            f"{os.getpid()}::{threading.get_ident()}: Streamlit callback received payload: {selected_cell_info}"
        )
        return Selection(
            selected_cell_info.col - 1,
            selected_cell_info.row,
            selected_cell_info.sorted_by,
        )
    else:
        print(
            f"{os.getpid()}::{threading.get_ident()}: Streamlit callback saw no payload"
        )
        return Selection(-1, -1, -1)


def _interpret_payload(payload: Selection) -> tuple[Any, Any]:
    """Interpret the payload and return the selected row and column."""
    # sorted_df = sort_df_by_selected_col(df, payload.sorted_by)
    selected_row = payload.row if payload.row >= 0 else -1
    selected_col = payload.col if payload.col >= 0 else -1

    return selected_row, selected_col


def fake_click(*args, **kwargs):
    parsed_payload: Selection = _retrieve_payload()
    selected_row, selected_col = _interpret_payload(parsed_payload)
    if selected_col != -1 or selected_row != -1:
        st.session_state["cell_position"] = selected_row, selected_col


class JSCallbackHandler(RequestHandler):
    def set_default_headers(self):
        # We hijack this method to store the JS payload
        try:
            payload: bytes = self.request.body
            print(
                f"{os.getpid()}::{threading.get_ident()}: Python received payload: {json.loads(payload)}"
            )
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON payload!")

        if payload_memory.buf[0] == 0:
            payload_memory.buf[: len(payload)] = payload
            print(
                f"{os.getpid()}::{threading.get_ident()}: Payload {payload} stored in shared memory"
            )


class CustomServer(Server):
    async def start(self):
        # Override the start of the Tornado server, so we can add custom handlers
        app = self._create_app()

        # Add a new handler
        app.default_router.add_rules(
            [
                (r"/js_callback", JSCallbackHandler),
            ]
        )

        # Our new rules go before the rule matching everything, reverse the list
        app.default_router.rules = list(reversed(app.default_router.rules))

        start_listening(app)
        await self._runtime.start()


# *´:°•.°+.*•´.*:˚.°*.˚•´.°:°•.°•.*•´.*:˚.°*.˚•´.°:°•.°+.*•´.*:*//
# *                          DATA SCHEMA                       *//
# *.•°:°.´+˚.*°.˚:*.´•*.+°.•°:´*.´•*.•°.•°:°.´:•˚°.*°.˚:*.´+°.•*//

st.subheader("Data Schema")
# with st.form("Submit", border=False, clear_on_submit=False):
if "table_name" not in st.session_state:
    st.session_state["table_name"] = ""
if "cell_position" not in st.session_state:
    st.session_state["cell_position"] = (0, 0)

if "create_analysis_input" not in st.session_state:
    st.session_state["create_analysis_input"] = {}
    
create_analysis_input = st.session_state["create_analysis_input"]

if "table_name" not in create_analysis_input:
    create_analysis_input["table_name"] = ""



create_analysis_input["table_name"] = st.text_input(
    "Table Name", create_analysis_input["table_name"]
)

if "user_input" not in create_analysis_input:
    create_analysis_input["user_input"] = pd.DataFrame()
if "previous_df" not in st.session_state:
    st.session_state.previous_df = pd.DataFrame([])


if "category_schema" not in create_analysis_input:
    create_analysis_input["category_schema"] = {}

if "schema_types" not in st.session_state:
    st.session_state.schema_types = []

if "user_input_changed" not in st.session_state:
    st.session_state.user_input_changed = 0
st.write(st.session_state.user_input_changed)

df = pd.DataFrame(columns=["name", "units", "type"])
if "last_user_input" in create_analysis_input and (st.session_state['user_input_changed'] == 0 or st.session_state['user_input_changed'] == 1):
    df = create_analysis_input["last_user_input"].reset_index(drop=True)
    # st.session_state.user_input_changed = False
schema_types = ["Integer", "Varchar", "String", "Float", "Category"]

html_contents = """
<script defer>
const fakeButton = window.parent.document.querySelector("[data-testid^='stBaseButton-primary']");
const tbl = window.parent.document.querySelector("[data-testid^='stDataFrameResizable']");
const canvas = window.parent.document.querySelector("[data-testid^='data-grid-canvas']");
let sortedBy = 1
function sendPayload(obj) {
    payloadStr = JSON.stringify(obj);
    window.sessionStorage.setItem("payload", payloadStr);
    fetch('/js_callback', {
        method: 'POST',
        body: payloadStr,
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => {
        fakeButton.click();
    });    
}
function updateColumnValue() {
    const headers = canvas.querySelectorAll('th[role="columnheader"]');
    let arrowFound = false;
    
    headers.forEach(header => {
        const textContent = header.textContent.trim();
        const colIndex = parseInt(header.getAttribute('aria-colindex'), 10);
        if (textContent.startsWith('↑')) {
            sortedBy = colIndex;
            arrowFound = true;
        } else if (textContent.startsWith('↓')) {
            sortedBy = -colIndex;
            arrowFound = true;
        }
    });
    if (!arrowFound) {
        sortedBy = 1;
    }    
    console.log(`Sorting column is now: ${sortedBy}`);
}
const sortObserver = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
        if (mutation.type === 'characterData' || mutation.type === 'childList') {
            updateColumnValue();
        }
    });
}); 
// Observe changes in the canvas element and its subtree
sortObserver.observe(canvas, {
    characterData: true,
    childList: true,
    subtree: true
});
function handleTableClick(event) {
    // MutationObserver callback function
    const cellObserverCallback = (mutationsList, observer) => {
        for (const mutation of mutationsList) {
            if (mutation.type === 'attributes' && mutation.attributeName === 'aria-selected') {
                const target = mutation.target;
                if (target.tagName === 'TD' && target.getAttribute('aria-selected') === 'true') {
                    cellCoords = target.id.replace('glide-cell-','').replace('-',',');
                    console.log(`Detected click on cell {${cellCoords}}, sorted by column "${sortedBy}"`);
                    observer.disconnect(); // Stop observing once the element is found                    
                    sendPayload({"action": "click", "cellId": cellCoords, "sortedByCol": sortedBy});                    
                }
            }
        }
    };
    // Create a MutationObserver
    const cellObserver = new MutationObserver(cellObserverCallback);  
    // Observe changes in attributes in the subtree of the canvas element
    cellObserver.observe(canvas, { attributes: true, subtree: true });
}
tbl.addEventListener('click', handleTableClick)
console.log("Event listeners added!");
</script>
"""


def schema_container():
    # def update_user_input_changed():
    #     st.session_state.user_input_changed = -1

    col1, col2 = st.columns([0.7, 0.3])

    conlumn_config = {
        "type": st.column_config.SelectboxColumn(
            "Type",
            options=schema_types,
            default="Integer",
        ),
        "name": st.column_config.TextColumn("Column Name"),
        "units": st.column_config.TextColumn("Units (e.g.lbs, kg, MM/dd/yyyy)"),
    }
    create_analysis_input["user_input"] = col1.data_editor(
        df,
        column_config=conlumn_config,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        # on_change=update_user_input_changed()
    )

    st.session_state.schema_types = create_analysis_input["user_input"]["type"].tolist()
    if "category_df" not in st.session_state:
        st.session_state.category_df = {}

    if "active_category" not in st.session_state:
        st.session_state.active_category = [False, -1]

    def store_df(index):
        if str(index) in st.session_state.category_df:
            st.session_state.category_df[index] = create_analysis_input[
                "category_schema"
            ][index].reset_index(drop=True)

    for index, entry in enumerate(create_analysis_input["user_input"]["type"]):
        if (
            entry == "Category" or entry not in schema_types
        ) and index == st.session_state["cell_position"][0]:
            st.session_state.active_category = [True, index]
            if index not in st.session_state.category_df:
                print("category_df not found")
                st.session_state.category_df[index] = pd.DataFrame(columns=["Category"])

            height = 5 + 35 * index
            col2.html(f"<p style='height: {height}px;'></p>")
            create_analysis_input["category_schema"][index] = col2.data_editor(
                st.session_state.category_df[index],
                column_config={
                    "Category": st.column_config.TextColumn(),
                },
                num_rows="dynamic",
                hide_index=True,
                use_container_width=True,
                # on_change=store_df(index),
            )

            st.session_state.category_df[index] = create_analysis_input[
                "category_schema"
            ][index].reset_index(drop=True)


schema_container()

# # Create a fake button:
st.button("", key="fakeButton", on_click=fake_click, type="primary")
st.markdown(
    """
    <style>
    div[data-testid="stTextInput"][data-st-key="CELL_ID"] {
        visibility: hidden;
    }
    button[kind="primary"] {
        visibility: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
html(html_contents)

st.write(f"position: {st.session_state.cell_position}")
st.write(create_analysis_input)
st.write(create_analysis_input["category_schema"])
st.write(st.session_state.schema_types)


column_name = create_analysis_input["user_input"].get(
    "Column Name", ""
)


st.divider()

validation_css = {
    "init": """
        {
            background-color: #FFFFFF;
            border-radius: 10px;
            padding: 15px;
        }
        """,
    True: """
            {
                background-color: #d7f8d8;
                border-radius: 10px;
                padding: 15px;
            }
            """,
    False: """
            {
                background-color: #f8d7da;
                border-radius: 10px;
                padding: 15px;
            }
            """,
}

# *´:°•.°+.*•´.*:˚.°*.˚•´.°:°•.°•.*•´.*:˚.°*.˚•´.°:°•.°+.*•´.*:*//
# *                          THREAT MODEL                      *//
# *.•°:°.´+˚.*°.˚:*.´•*.+°.•°:´*.´•*.•°.•°:°.´:•˚°.*°.˚:*.´+°.•*//

# ********** SESSION INITILIAZARION **********
if "threat_model" not in create_analysis_input:
    create_analysis_input["threat_model"] = ""
if "selected_providers" not in create_analysis_input:
    create_analysis_input["selected_providers"] = []
if "isvalid_threat_model" not in st.session_state:
    st.session_state["isvalid_threat_model"] = "init"
if "isvalid_analysis_details" not in st.session_state:
    st.session_state["isvalid_analysis_details"] = "init"
if "isvalid_sql" not in st.session_state:
    st.session_state["isvalid_sql"] = True

st.subheader("Threat Model")

cloud_providers = [
    "AWS",
    "Microsoft Azure",
    "Google Cloud",
    "Chameleon Open Cloud",
    "Cloud 1",
    "Cloud 2",
]

threat_models = ["Semi-Honest", "Malicious"]


def threat_model_container() -> None:
    css_style = (
        "init"
        if st.session_state.isvalid_threat_model == "init"
        else st.session_state.isvalid_threat_model == 1
    )
    with stylable_container(
        key="thread_model",
        css_styles=validation_css[css_style],
    ):
        col1, col2 = st.columns(2)
        new_threat_model = col1.radio(
            "Threat Model",
            options=threat_models,
            label_visibility="collapsed",
            key="t1",
        )

        # Detect if the threat model has been changed
        if new_threat_model != create_analysis_input.get("threat_model", ""):
            create_analysis_input["threat_model"] = new_threat_model
            st.session_state.threat_model_changed = True
        else:
            st.session_state.threat_model_changed = False

        col2.markdown("##### Cloud Providers")

        if st.session_state.threat_model_changed:
            if (
                create_analysis_input["threat_model"]
                == "Semi-Honest"
            ):
                create_analysis_input["selected_providers"] = (
                    random.sample(cloud_providers, 3)
                )

            elif (
                create_analysis_input["threat_model"] == "Malicious"
            ):
                create_analysis_input["selected_providers"] = (
                    random.sample(cloud_providers, 4)
                )

        selected_providers: list[str] = create_analysis_input[
            "selected_providers"
        ]
        for provider in cloud_providers:
            is_selected = col2.toggle(
                provider,
                key=f"toggle_{provider}",
                value=provider in selected_providers,
            )

            # Update selected_providers based on toggle state
            if is_selected and provider not in selected_providers:
                selected_providers.append(provider)
            elif not is_selected and provider in selected_providers:
                selected_providers.remove(provider)
                
    if st.session_state.isvalid_threat_model == 2:
        st.error(
            "Error: In the Semi-Honest threat model, you must select at least 3 cloud providers."
        )
    elif st.session_state.isvalid_threat_model == 3:
        st.error(
            "Error: In the Malicious threat model, you must select at least 4 cloud providers."
        )


threat_model_container()
st.write(create_analysis_input["selected_providers"])
st.divider()

# *´:°•.°+.*•´.*:˚.°*.˚•´.°:°•.°•.*•´.*:˚.°*.˚•´.°:°•.°+.*•´.*:*//
# *                       ANALYSIS DETAILS                     *//
# *.•°:°.´+˚.*°.˚:*.´•*.+°.•°:´*.´•*.•°.•°:°.´:•˚°.*°.˚:*.´+°.•*//

st.subheader("Analysis Details")

type_mapping = {
    "String": "TEXT",
    "Varchar": "TEXT",
    "Integer": "INT",
    "Float": "FLOAT",
    "Boolean": "BOOLEAN",
    "Category": "ENUM",
}

if "temp_enums" not in st.session_state:
    st.session_state["temp_enums"] = []


def create_table_sql() -> str:
    print("create_table_sql")
    user_input = create_analysis_input["user_input"]
    table_name = create_analysis_input["table_name"]
    columns = user_input.iloc[:, 0]
    types = user_input.iloc[:, 2]

    sql_statements = []

    create_table_sql = f"CREATE TABLE {table_name} (\n"

    # Iterate through columns and types to create the column definitions
    for index, (column, data_type) in enumerate(zip(columns, types)):
        # Check if the data type is ENUM
        if data_type == "Category":
            # Fetch the finite set for the ENUM from category_schema
            enum_values = create_analysis_input["category_schema"][index]["Category"].dropna().tolist()

            # Format the ENUM values for SQL (e.g., 'VALUE1', 'VALUE2', ...)
            enum_str = ", ".join([f"'{value}'" for value in enum_values])

            # Define the ENUM type in SQL
            enum_type_name = f"{column}_enum"
            enum_type_sql = f"CREATE TYPE {enum_type_name} AS ENUM ({enum_str});"
            sql_statements.append(enum_type_sql)

            # Use the ENUM type in the CREATE TABLE statement
            create_table_sql += f"    {column} {enum_type_name},\n"
        else:
            print(f"|create_table_sql|: {data_type}")
            # Map other data types as usual
            data_type = type_mapping[data_type]
            create_table_sql += f"    {column} {data_type},\n"

    create_table_sql = create_table_sql.rstrip(",\n") + "\n);"
    sql_statements.append(create_table_sql)

    # Join all statements
    full_sql = "\n".join(sql_statements)
    return full_sql


def find_enums():
    user_input = create_analysis_input["user_input"]
    columns = user_input.iloc[:, 0]
    types = user_input.iloc[:, 2]
    for column, data_type in zip(columns, types):
        # Check if the data type is ENUM
        if data_type == "Category":
            # Fetch the finite set for the ENUM from category_schema
            enum_values = create_analysis_input["category_schema"]
            print(f"|find_enums|: enum_values:{enum_values}")

            # Define the ENUM type in SQL
            enum_type_name = f"{column}_enum"
            st.session_state["temp_enums"].append(enum_type_name)


def drop_enums_sql() -> str:
    """generate sql for droping temporary enums for sql validation
    Returns:
        str: sql to drop temporary enums
    """
    sql = ""
    if st.session_state["temp_enums"] != []:
        for _, enum_name in enumerate(st.session_state["temp_enums"]):
            sql += f"DROP TYPE IF EXISTS {enum_name};\n"
    return sql


def drop_table_sql() -> str:
    """generate sql for droping temporary table for sql validation
    Returns:
        str: sql to drop temporary table
    """
    table_name = create_analysis_input['table_name']
    sql = f"DROP TABLE IF EXISTS {table_name};"
    return sql


def validate_sql():
    engine = create_engine(
        "postgresql+psycopg2://user1:12345678!@localhost:5432/shield_query"
    )
    query = create_analysis_input["query"]
    
    find_enums()
    try:
        
        with engine.connect() as conn:
            print("drop_table_sql")
            conn.execute(sqlalchemy.text(drop_table_sql()))
            drop_enums_statement = drop_enums_sql()
            if drop_enums_statement != "":  # Only execute if it's not empty
                print(f"Executing drop_enums_sql: \'{drop_enums_statement}\'")
                conn.execute(sqlalchemy.text(drop_enums_statement))
            print("create_table_sql")
            conn.execute(sqlalchemy.text(create_table_sql()))
            print("query", )
            conn.execute(sqlalchemy.text(query))
            print("drop_table_sql")
            conn.execute(sqlalchemy.text(drop_table_sql()))
            print("drop_enums_sql")
            if drop_enums_statement != "":
                conn.execute(sqlalchemy.text(drop_enums_statement))
            st.session_state["temp_enums"] = []
            return True
    except Exception as e:
        print(e)
        return False

if "query_name" not in create_analysis_input:
    create_analysis_input["query_name"] = ""
if "query" not in create_analysis_input:
    create_analysis_input["query"] = ""
if "description" not in create_analysis_input:
    create_analysis_input["description"] = ""
    
def analysis_details_container() -> None:
    if st.session_state.isvalid_analysis_details == "init":
        css_style = "init"
    else:
        css_style = st.session_state.isvalid_analysis_details == 1
    with stylable_container(
        key="analysis_details_model",
        css_styles=validation_css[css_style],
    ):
        create_analysis_input["query_name"] = st.text_input("Query Name", create_analysis_input["query_name"])
        create_analysis_input["query"] = st.text_area("Input Query Here", create_analysis_input["query"])
        create_analysis_input["description"] = st.text_area("Description", create_analysis_input["description"])
        

    if st.session_state.isvalid_analysis_details == 2:
        st.error("Error: No fields should be empty.")
    elif st.session_state.isvalid_analysis_details == 3:
        st.error("Error: Invalid SQL query.")


analysis_details_container()
st.write(
    [
        create_analysis_input["query_name"],
        create_analysis_input["query"],
        create_analysis_input["description"],
    ]
)
st.divider()

if "Submit" not in st.session_state:
    st.session_state["Submit"] = False

st.subheader("Complete Registration")
st.session_state.submitted = st.button("Submit")


# *´:°•.°+.*•´.*:˚.°*.˚•´.°:°•.°•.*•´.*:˚.°*.˚•´.°:°•.°+.*•´.*:*//
# *                       INPUT VALIDATION                     *//
# *.•°:°.´+˚.*°.˚:*.´•*.+°.•°:´*.´•*.•°.•°:°.´:•˚°.*°.˚:*.´+°.•*//
def validate_threat_model() -> bool:
    if create_analysis_input["threat_model"] == "Semi-Honest":
        if len(create_analysis_input['selected_providers']) >= 3:
            st.session_state.isvalid_threat_model = 1
            return True
        elif len(create_analysis_input['selected_providers']) < 3:
            st.session_state.isvalid_threat_model = 2
            return False
    if create_analysis_input["threat_model"] == "Malicious":
        if len(create_analysis_input['selected_providers']) >= 4:
            st.session_state.isvalid_threat_model = 1
            return True
        elif len(create_analysis_input['selected_providers']) < 4:
            st.session_state.isvalid_threat_model = 3
            return False
    return False


def validate_analysis_details() -> bool:
    if (
        create_analysis_input["query_name"] == ""
        or create_analysis_input["query"] == ""
        or create_analysis_input["description"] == ""
    ):
        st.session_state["isvalid_analysis_details"] = 2
        return False
    else:
        isValid = validate_sql()
        if isValid:
            st.session_state["isvalid_analysis_details"] = 1
            return True
        else:
            st.session_state["isvalid_analysis_details"] = 3
            return False


if st.session_state.submitted:
    if "disabled" not in st.session_state:
        st.session_state["disabled"] = False

    def disable():
        st.session_state["disabled"] = True

    disable()
    create_analysis_input["last_user_input"] = create_analysis_input["user_input"]
    st.session_state["Submit"] = st.session_state.submitted

    if validate_threat_model() and validate_analysis_details():
        st.session_state.user_input_changed = 1
        # st.write(st.session_state)
        # print(create_analysis_input["user_input"])
        # user_input_json = create_analysis_input["user_input"].to_json(
        #     orient="records"
        # )
        # print(user_input_json)
        st.rerun()
    else:
        st.rerun()

if (
    st.session_state["isvalid_analysis_details"] == 1
    and st.session_state["isvalid_analysis_details"] == 1
):
    st.success("Success")




if __name__ == "__main__":
    import streamlit.web.bootstrap

    if "__streamlitmagic__" not in locals():
        # Code adapted from bootstrap.py in streamlit
        streamlit.web.bootstrap._fix_sys_path(__file__)
        streamlit.web.bootstrap._fix_tornado_crash()
        streamlit.web.bootstrap._fix_sys_argv(__file__, [])
        streamlit.web.bootstrap._fix_pydeck_mapbox_api_warning()
        # streamlit.web.bootstrap._fix_pydantic_duplicate_validators_error()

        server = CustomServer(__file__, is_hello=False)

        async def run_server():
            await server.start()
            streamlit.web.bootstrap._on_server_start(server)
            streamlit.web.bootstrap._set_up_signal_handler(server)
            await server.stopped

        asyncio.run(run_server())
