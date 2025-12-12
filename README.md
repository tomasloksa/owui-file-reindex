# Open WebUI File Reindex Script

A Python script for reindexing files in Open WebUI after a vector database migration. This script processes standalone files and restores their vector database collections without deleting any existing data.

Tested on OWUI v0.6.41.

## What It Does

This script reindexes all standalone files in Open WebUI by:
- Scanning all files in the database
- Identifying files that need reindexing (missing or empty vector collections)
- Processing each file through Open WebUI's indexing pipeline
- Creating or updating `file-{id}` collections in the vector database

**Note:** Files stored in folders are also reindexed by this script. If you previously attempted to restore folder files separately and they were already restored, the script will detect this and skip them automatically.

## How It Works

The script:
1. Initializes the Open WebUI application context with all necessary dependencies
2. Connects to the existing database and vector store
3. Retrieves all files from the database
4. For each file:
   - Checks if it has content to process
   - Verifies if a vector collection already exists with documents
   - Skips files that are already indexed
   - Reindexes files that are missing or have empty collections

### Data Access

The script accesses data by:
- Using Open WebUI's internal models (`Files`, `Users`) to read from the PostgreSQL database
- Leveraging the vector database client (Qdrant/Chroma/etc.) configured in Open WebUI
- Processing files through Open WebUI's existing `process_file` function
- Running within the application context to access all initialized components

## Important Notes

### ⚠️ Backup Your Data
**Always backup your database before running this script**, even though it does not delete anything. This is a safety precaution for any data migration process.

### Container Scaling Required
When running this script in an Azure container (or similar environment):
- **Scale up the container** before running to prevent OOM (Out of Memory) errors on larger files
- **Do not turn off the original app** - the script requires the app to be running and initialized
- The script performs memory cleanup every 10 files, but sufficient container resources are still needed

### Resumable Process
If the process fails or is interrupted:
- **You can safely run it again**
- The script will automatically skip already indexed files
- Progress is logged so you can track where it continues from

### Knowledge Bases
- Knowledge bases can be restored using the Open WebUI UI
- Reindexing standalone files **might** restore associated knowledge bases (behavior uncertain - not tested with knowledge bases)

## Usage

### Quick Start

1. **Set up the new vector store** (ensure Open WebUI is configured to use it)

2. **Navigate to the Open WebUI backend directory:**
```bash
cd /app/backend
```

3. **Download the script:**
```bash
curl -o reindex_all.py https://raw.githubusercontent.com/tomasloksa/owui-file-reindex/refs/heads/main/reindex_all.py
```

4. **Run the script:**
```bash
python3 reindex_all.py
```

**Note:** The script must be run from `/app/backend` (or wherever the `open_webui` package is located) to access the necessary Python imports.

## Output

The script provides detailed logging including:
- Progress percentage and file counts
- Files being processed with their IDs and filenames
- Memory cleanup notifications
- Summary of successful, skipped, and failed files
- Total execution time
- List of any failed files with error messages

Example output:
```
[REINDEX] Starting complete reindexing process
[REINDEX] App initialized. Embedding function: <class 'sentence_transformers.SentenceTransformer'>
[REINDEX] Checking 150 files for standalone collections
[REINDEX] Progress: 50/150 (33.3%) - Processed: 35, Skipped: 15
[REINDEX] [51/150 - 34.0%] Reindexing file: document.pdf (ID: abc123)
...
[REINDEX] REINDEXING COMPLETE!
[REINDEX] Total time: 245.30 seconds (4.1 minutes)
[REINDEX] Standalone files reindexed: 135
```

## Requirements

- Python 3
- Open WebUI installation with initialized database
- Access to Open WebUI's Python environment (dependencies included)
- Sufficient container/system resources for processing files  
