import streamlit as st
from src.db import execute, now
from utils.helpers import fetch_documents, fetch_features, ws_id
from src.llm import generate_implementation_roadmap

def show_roadmap():
    st.markdown("## Implementation Roadmap")
    st.caption("AI translates your approved PRDs into actionable 2-Sprint execution plans.")
    st.write("---")

    # Fetch all documents
    docs = fetch_documents()
    if docs.empty:
        st.info("No documents available. Please generate a PRD from the Reports tab first.")
        return

    # Filter for PRDs
    prds = docs[docs["doc_type"] == "PRD"]
    if prds.empty:
        st.info("No PRDs available yet. Please generate a PRD from the Reports tab first.")
        return

    # PRD/Roadmap documents are keyed by feature_requests.title, which is
    # truncated to ~70 characters (with an ellipsis) for compact use
    # elsewhere in the app (e.g. the Dashboard's chart legend). That reads
    # as a sentence cut off mid-way when shown here at full width in the
    # dropdown, so the full, untruncated feedback text is looked up from
    # feature_requests.description for display -- matching still runs on
    # the original (truncated) title, so nothing downstream changes.
    features = fetch_features()
    full_text_by_title = {}
    if not features.empty:
        for _, f in features.iterrows():
            full_text_by_title[f["title"]] = (f.get("description") or f["title"] or "").strip()

    def _full_text(title):
        return full_text_by_title.get(title, title)

    # Dropdown to select which PRD to plan
    selected_title = st.selectbox(
        "Select Feature to Plan", prds["title"].tolist(), format_func=_full_text
    )
    selected_prd = prds[prds["title"] == selected_title].iloc[0]
    selected_display = _full_text(selected_title)

    # Look for an existing Roadmap document for this specific feature
    roadmaps = docs[(docs["doc_type"] == "Roadmap") & (docs["title"] == selected_title)]

    # If no roadmap exists yet, show the generation button
    if roadmaps.empty:
        st.warning(f"No Implementation Roadmap exists for '{selected_display}' yet.")
        if st.button("Generate 2-Sprint Roadmap", type="primary", use_container_width=True):
            with st.spinner("AI is analyzing the PRD and generating the execution plan..."):
                try:
                    # Pass the raw PRD text to the AI to write the roadmap
                    roadmap_plan = generate_implementation_roadmap(selected_prd["content"])
                    
                    # Save the new roadmap as its own separate document
                    execute(
                        "INSERT INTO documents (workspace_id, doc_type, title, content, created_at) VALUES (?,?,?,?,?)",
                        (ws_id(), "Roadmap", selected_title, roadmap_plan, now())
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to generate roadmap: {e}")
                    
    # If it does exist, render it cleanly
    else:
        roadmap_text = roadmaps.iloc[0]["content"]
        with st.container(border=True):
            st.markdown(roadmap_text)
            
        st.write("")
        if st.button("Delete & Regenerate Roadmap", use_container_width=True):
            execute("DELETE FROM documents WHERE id = ?", (int(roadmaps.iloc[0]["id"]),))
            st.rerun()