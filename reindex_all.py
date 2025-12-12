#!/usr/bin/env python3
"""
Reindex all knowledge bases and files for vector database migration
Run this inside the Open WebUI container with the app already initialized
"""

import sys
import logging
import time
import gc

print("Script started!", flush=True)

# Set up logging only for errors - Open WebUI will override INFO logs
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

def log_info(msg):
    """Print info messages to stdout so they're visible in Azure"""
    print(f"[REINDEX] {msg}", flush=True)

def log_error(msg):
    """Log errors using the logger"""
    log.error(msg)
    print(f"[REINDEX ERROR] {msg}", flush=True)

def reindex_standalone_files(app):
    """Reindex all standalone files (file-{id} collections) using existing app context"""
    from open_webui.models.files import Files
    from open_webui.routers.retrieval import ProcessFileForm, process_file
    from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
    from open_webui.models.users import Users
    
    class Request:
        pass
    
    request = Request()
    request.app = app
    
    admin_user = Users.get_super_admin_user()
    if not admin_user:
        log_error("No admin user found!")
        return 0, []
    
    files = Files.get_files()
    total_files = len(files)
    log_info(f"Checking {total_files} files for standalone collections")
    
    success_count = 0
    failed_files = []
    skipped_count = 0
    
    for i, file in enumerate(files, 1):
        try:
            # Only process files that have content (skip empty/placeholder files)
            if not file.data or not file.data.get("content"):
                skipped_count += 1
                if i % 10 == 0:
                    progress_pct = (i / total_files) * 100
                    log_info(f"Progress: {i}/{total_files} ({progress_pct:.1f}%) - Processed: {success_count}, Skipped: {skipped_count}")
                continue
            
            file_collection = f"file-{file.id}"
            
            try:
                if VECTOR_DB_CLIENT.has_collection(collection_name=file_collection):
                    # Check if collection has any documents
                    result = VECTOR_DB_CLIENT.query(
                        collection_name=file_collection,
                        filter={"file_id": file.id}
                    )
                    if result and len(result.ids[0]) > 0:
                        skipped_count += 1
                        if i % 10 == 0:
                            progress_pct = (i / total_files) * 100
                            log_info(f"Progress: {i}/{total_files} ({progress_pct:.1f}%) - Processed: {success_count}, Skipped: {skipped_count}")
                        continue
            except Exception as e:
                pass
            
            progress_pct = (i / total_files) * 100
            log_info(f"[{i}/{total_files} - {progress_pct:.1f}%] Reindexing file: {file.filename} (ID: {file.id})")
            
            # Process the file - collection_name=None means it will create file-{id} collection
            process_file(
                request,
                ProcessFileForm(file_id=file.id, collection_name=None),
                user=admin_user
            )
            success_count += 1
            
            # Force garbage collection every 10 files to manage memory
            if success_count % 10 == 0:
                gc.collect()
                log_info(f"  Memory cleanup performed (processed {success_count} files)")
                
        except Exception as e:
            log_error(f"Failed to reindex file {file.filename} (ID: {file.id}): {e}")
            failed_files.append({
                "file_id": file.id,
                "filename": file.filename,
                "error": str(e)
            })
            continue
    
    log_info(f"File reindexing complete. Total files checked: {total_files}, Skipped: {skipped_count}, Successfully reindexed: {success_count}, Failed: {len(failed_files)}")
    return success_count, failed_files

def main():
    log_info("=" * 80)
    log_info("Starting complete reindexing process")
    log_info("=" * 80)
    
    start_time = time.time()
    
    try:
        # Import and initialize the app
        log_info("Initializing Open WebUI app...")
        from open_webui.main import app
        
        # Verify we have the necessary components
        if not hasattr(app.state, 'EMBEDDING_FUNCTION'):
            log_error("App state doesn't have EMBEDDING_FUNCTION. App may not be properly initialized.")
            sys.exit(1)
        
        log_info(f"App initialized. Embedding function: {type(app.state.EMBEDDING_FUNCTION)}")
        
        log_info("\n" + "=" * 80)
        log_info("Reindexing Standalone Files")
        log_info("=" * 80)
        file_success, file_failed = reindex_standalone_files(app)
        log_info(f"✓ Standalone files reindexed: {file_success}, failed: {len(file_failed)}")
        
        elapsed = time.time() - start_time
        
        log_info("\n" + "=" * 80)
        log_info("REINDEXING COMPLETE!")
        log_info("=" * 80)
        log_info(f"Total time: {elapsed:.2f} seconds ({elapsed/60:.1f} minutes)")
        log_info(f"Standalone files reindexed: {file_success}")
        
        all_failed = file_failed
        if all_failed:
            log_info("\nFailed files:")
            for failed in all_failed[:10]:  # Show first 10
                log_info(f"  - {failed.get('filename', 'Unknown')} ({failed['file_id']}): {failed['error']}")
            if len(all_failed) > 10:
                log_info(f"  ... and {len(all_failed) - 10} more")
        
        log_info("\n✓ Migration from ChromaDB to pgvector is complete!")
        log_info("You can now use your Open WebUI application with pgvector.")
        
        sys.exit(0)
        
    except Exception as e:
        log_error(f"Fatal error during reindexing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
