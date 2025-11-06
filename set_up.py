import os

# Define the folder and file structure
structure = {
    "handlers": [
        "user_handler.py",
        "admin_handler.py",
        "paraphrase_handler.py"
    ],
    "utils": [
        "firebase_utils.py",
        "gemini_utils.py",
        "auth_utils.py",
        "helpers.py"
    ]
}

# Create folders and empty files
for folder, files in structure.items():
    os.makedirs(folder, exist_ok=True)
    for file in files:
        file_path = os.path.join(folder, file)
        open(file_path, "a").close()

# Create root-level files
for root_file in ["main.py", ".env", "requirements.txt"]:
    open(root_file, "a").close()

print("✅ Folder and file structure created successfully!")
