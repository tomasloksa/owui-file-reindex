#!/usr/bin/env python3
"""
Reindex all knowledge bases and files for vector database migration
Run this inside the Open WebUI container with the app already initialized
"""

import sys
import logging
import time

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

def reindex_knowledge_bases(app):
    """Reindex all knowledge bases using the existing app context"""
    from open_webui.models.knowledge import Knowledges
    from open_webui.models.files import Files
    from open_webui.routers.retrieval import ProcessFileForm, process_file
    from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
    from open_webui.models.users import Users
    
    # Create request object from app
    class Request:
        pass
    
    request = Request()
    request.app = app
    
    # Get admin user
    admin_user = Users.get_super_admin_user()
    if not admin_user:
        log_error("No admin user found!")
        return 0, []
    
    knowledge_bases = Knowledges.get_knowledge_bases()
    total_kbs = len(knowledge_bases)
    log_info(f"Starting reindexing for {total_kbs} knowledge bases")
    
    deleted_knowledge_bases = []
    success_count = 0
    
    for kb_idx, knowledge_base in enumerate(knowledge_bases, 1):
        if not knowledge_base.data or not isinstance(knowledge_base.data, dict):
            log_info(f"Knowledge base {knowledge_base.id} has no data. Deleting.")
            try:
                Knowledges.delete_knowledge_by_id(id=knowledge_base.id)
                deleted_knowledge_bases.append(knowledge_base.id)
            except Exception as e:
                log_error(f"Failed to delete invalid knowledge base {knowledge_base.id}: {e}")
            continue
        
        try:
            file_ids = knowledge_base.data.get("file_ids", [])
            files = Files.get_files_by_ids(file_ids)
            
            progress_pct = (kb_idx / total_kbs) * 100
            log_info(f"[{kb_idx}/{total_kbs} - {progress_pct:.1f}%] Reindexing knowledge base: {knowledge_base.name} ({knowledge_base.id}) - {len(files)} files")
            
            try:
                if VECTOR_DB_CLIENT.has_collection(collection_name=knowledge_base.id):
                    VECTOR_DB_CLIENT.delete_collection(collection_name=knowledge_base.id)
                    log_info(f"Deleted old collection for {knowledge_base.id}")
            except Exception as e:
                log_error(f"Error deleting collection {knowledge_base.id}: {str(e)}")
                continue
            
            failed_files = []
            for i, file in enumerate(files, 1):
                try:
                    log_info(f"  Processing file {i}/{len(files)}: {file.filename}")
                    process_file(
                        request,
                        ProcessFileForm(file_id=file.id, collection_name=knowledge_base.id),
                        user=admin_user,
                    )
                except Exception as e:
                    log_error(f"  Error processing file {file.filename} (ID: {file.id}): {str(e)}")
                    failed_files.append({"file_id": file.id, "error": str(e)})
                    continue
            
            if failed_files:
                log_info(f"Failed to process {len(failed_files)} files in knowledge base {knowledge_base.id}")
            else:
                success_count += 1
                log_info(f"✓ Successfully reindexed knowledge base: {knowledge_base.name}")
                
        except Exception as e:
            log_error(f"Error processing knowledge base {knowledge_base.id}: {str(e)}")
            continue
    
    log_info(f"Knowledge base reindexing completed. Success: {success_count}, Deleted: {len(deleted_knowledge_bases)}")
    return success_count, deleted_knowledge_bases


def reindex_standalone_files(app):
    """Reindex all standalone files (file-{id} collections) using existing app context"""
    from open_webui.models.files import Files
    from open_webui.routers.retrieval import ProcessFileForm, process_file
    from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
    from open_webui.models.users import Users
    
    # Create request object from app
    class Request:
        pass
    
    request = Request()
    request.app = app
    
    # Get admin user
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
            
            # Check if file already has embeddings in pgvector
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
                pass  # No collection exists, will create new one
            
            progress_pct = (i / total_files) * 100
            log_info(f"[{i}/{total_files} - {progress_pct:.1f}%] Reindexing file: {file.filename} (ID: {file.id})")
            
            # Delete old collection if it exists
            try:
                if VECTOR_DB_CLIENT.has_collection(collection_name=file_collection):
                    VECTOR_DB_CLIENT.delete_collection(collection_name=file_collection)
            except Exception as e:
                pass
            
            # Process the file - collection_name=None means it will create file-{id} collection
            process_file(
                request,
                ProcessFileForm(file_id=file.id, collection_name=None),
                user=admin_user
            )
            success_count += 1
                
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


def reindex_folder_files(app):
    """Reindex all files referenced in folders"""
    from open_webui.models.folders import Folders
    from open_webui.models.files import Files
    from open_webui.models.users import Users
    from open_webui.routers.retrieval import ProcessFileForm, process_file
    from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
    
    # Create request object from app
    class Request:
        pass
    
    request = Request()
    request.app = app
    
    # Get admin user
    admin_user = Users.get_super_admin_user()
    if not admin_user:
        log_error("No admin user found!")
        return 0, []
    
    # Get all users and then get their folders
    all_users = Users.get_users()
    total_users = len(all_users)
    log_info(f"Checking folders for {total_users} users")
    
    success_count = 0
    failed_files = []
    processed_file_ids = set()  # Track processed files to avoid duplicates
    total_folders = 0
    total_file_refs = 0
    
    for user_idx, user in enumerate(all_users, 1):
        user_folders = Folders.get_folders_by_user_id(user.id)
        total_folders += len(user_folders)
        
        for folder in user_folders:
            if not folder.data or "files" not in folder.data:
                continue
            
            folder_files = folder.data.get("files", [])
            if not folder_files:
                continue
            
            total_file_refs += len(folder_files)
            user_progress_pct = (user_idx / total_users) * 100
            log_info(f"[User {user_idx}/{total_users} - {user_progress_pct:.1f}%] Processing folder '{folder.name}' ({user.email}) with {len(folder_files)} file references")
            
            for file_ref in folder_files:
                if file_ref.get("type") != "file":
                    continue  # Skip collections, only process files
                
                file_id = file_ref.get("id")
                if not file_id or file_id in processed_file_ids:
                    continue  # Skip if already processed
                
                processed_file_ids.add(file_id)
                
                try:
                    file = Files.get_file_by_id(file_id)
                    if not file:
                        continue
                    
                    # Only process files that have content
                    if not file.data or not file.data.get("content"):
                        continue
                    
                    file_collection = f"file-{file.id}"
                    
                    # Check if file already has embeddings in pgvector
                    try:
                        if VECTOR_DB_CLIENT.has_collection(collection_name=file_collection):
                            # Check if collection has any documents
                            result = VECTOR_DB_CLIENT.query(
                                collection_name=file_collection,
                                filter={"file_id": file.id}
                            )
                            if result and len(result.ids[0]) > 0:
                                continue
                    except Exception as e:
                        pass
                    
                    log_info(f"  Reindexing file: {file.filename} (ID: {file.id})")
                    
                    # Delete old collection if it exists
                    try:
                        if VECTOR_DB_CLIENT.has_collection(collection_name=file_collection):
                            VECTOR_DB_CLIENT.delete_collection(collection_name=file_collection)
                    except Exception as e:
                        pass
                    
                    # Reprocess the file
                    process_file(
                        request,
                        ProcessFileForm(file_id=file.id, collection_name=None),
                        user=admin_user
                    )
                    success_count += 1
                        
                except Exception as e:
                    log_error(f"  Failed to reindex file {file_id}: {e}")
                    failed_files.append({
                        "file_id": file_id,
                        "error": str(e)
                    })
                    continue
    
    log_info(f"Folder files reindexing complete. Total users: {total_users}, Total folders: {total_folders}, Total file references: {total_file_refs}, Unique files found: {len(processed_file_ids)}, Success: {success_count}, Failed: {len(failed_files)}")
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
        
        # Step 1: Reindex knowledge bases
        log_info("\n" + "=" * 80)
        log_info("STEP 1: Reindexing Knowledge Bases")
        log_info("=" * 80)
        kb_success, kb_deleted = reindex_knowledge_bases(app)
        log_info(f"✓ Knowledge bases reindexed: {kb_success}, deleted: {len(kb_deleted)}")
        
        # Step 2: Reindex standalone files
        log_info("\n" + "=" * 80)
        log_info("STEP 2: Reindexing Standalone Files")
        log_info("=" * 80)
        file_success, file_failed = reindex_standalone_files(app)
        log_info(f"✓ Standalone files reindexed: {file_success}, failed: {len(file_failed)}")
        
        # Step 3: Reindex files in folders
        log_info("\n" + "=" * 80)
        log_info("STEP 3: Reindexing Files in Folders")
        log_info("=" * 80)
        folder_file_success, folder_file_failed = reindex_folder_files(app)
        log_info(f"✓ Folder files reindexed: {folder_file_success}, failed: {len(folder_file_failed)}")
        
        elapsed = time.time() - start_time
        
        log_info("\n" + "=" * 80)
        log_info("REINDEXING COMPLETE!")
        log_info("=" * 80)
        log_info(f"Total time: {elapsed:.2f} seconds ({elapsed/60:.1f} minutes)")
        log_info(f"Knowledge bases reindexed: {kb_success}")
        log_info(f"Standalone files reindexed: {file_success}")
        log_info(f"Folder files reindexed: {folder_file_success}")
        log_info(f"Total failed files: {len(file_failed) + len(folder_file_failed)}")
        
        all_failed = file_failed + folder_file_failed
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
