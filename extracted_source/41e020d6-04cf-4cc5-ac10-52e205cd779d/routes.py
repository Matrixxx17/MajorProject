from fastapi import APIRouter, HTTPException
from models import Note

router = APIRouter()

notes = []

@router.post("/notes", response_model=Note)
def create_note(note: Note):
    notes.append(note)
    return note

@router.get("/notes/{note_id}", response_model=Note)
def get_note(note_id: int):
    for note in notes:
        if note.id == note_id:
            return note
    raise HTTPException(status_code=404, detail="Note not found")
