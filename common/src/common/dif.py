from typing import Any, Dict, Tuple

def extract_diffs_for_firestore_and_audit(
    old: Dict[str, Any],
    new: Dict[str, Any],
    prefix: str = ""
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    firestore_update: Dict[str, Any] = {}
    audit_log: Dict[str, Any] = {}

    for key in new:
        full_key = f"{prefix}.{key}" if prefix else key

        if key not in old:
            firestore_update[full_key] = new[key]
            audit_log[full_key] = new[key]

        else:
            old_val = old[key]
            new_val = new[key]

            if isinstance(old_val, dict) and isinstance(new_val, dict):
                sub_update, sub_log = extract_diffs_for_firestore_and_audit(old_val, new_val, full_key)
                firestore_update.update(sub_update)
                audit_log.update(sub_log)

            elif isinstance(old_val, list) and isinstance(new_val, list):
                added = [item for item in new_val if item not in old_val]
                removed = [item for item in old_val if item not in new_val]

                if added or removed:
                    # En Firestore: reescribimos todo el array
                    firestore_update[full_key] = new_val
                    audit_log[full_key] = {
                        "added": added,
                        "removed": removed
                    }

            elif old_val != new_val:
                firestore_update[full_key] = new_val
                audit_log[full_key] = new_val

    return firestore_update, audit_log


old = {
    "nombre": "Pedro",
    "roles": ["admin", "editor"],
    "pepe": "Hola"
}

new = {
    "nombre": "Pedro Hurtado",
    #"roles": ["admin", "editor", "supervisor"]
    "roles": ["admin", "editor"]
}

firestore_update, audit_log = extract_diffs_for_firestore_and_audit(old, new)
print("----FIRESTORE UPDATE-----")
print(firestore_update)
print("----AUDIT LOG-----")
print(audit_log)
