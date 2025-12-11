#!/usr/bin/env python3
"""
Reindex all knowledge bases and files for vector database migration
Run this inside the Open WebUI container with the app already initialized
"""

import sys
import os
import logging
import time
import asyncio

print("Script started!", flush=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)
log.info("Logger initialized!")

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
        log.error("No admin user found!")
        return 0, []
    
    knowledge_bases = Knowledges.get_knowledge_bases()
    log.info(f"Starting reindexing for {len(knowledge_bases)} knowledge bases")
    
    deleted_knowledge_bases = []
    success_count = 0
    
    for knowledge_base in knowledge_bases:
        if not knowledge_base.data or not isinstance(knowledge_base.data, dict):
            log.warning(f"Knowledge base {knowledge_base.id} has no data. Deleting.")
            try:
                Knowledges.delete_knowledge_by_id(id=knowledge_base.id)
                deleted_knowledge_bases.append(knowledge_base.id)
            except Exception as e:
                log.error(f"Failed to delete invalid knowledge base {knowledge_base.id}: {e}")
            continue
        
        try:
            file_ids = knowledge_base.data.get("file_ids", [])
            files = Files.get_files_by_ids(file_ids)
            
            log.info(f"Reindexing knowledge base: {knowledge_base.name} ({knowledge_base.id}) - {len(files)} files")
            
            try:
                if VECTOR_DB_CLIENT.has_collection(collection_name=knowledge_base.id):
                    VECTOR_DB_CLIENT.delete_collection(collection_name=knowledge_base.id)
                    log.info(f"Deleted old collection for {knowledge_base.id}")
            except Exception as e:
                log.error(f"Error deleting collection {knowledge_base.id}: {str(e)}")
                continue
            
            failed_files = []
            for i, file in enumerate(files, 1):
                try:
                    log.info(f"  Processing file {i}/{len(files)}: {file.filename}")
                    process_file(
                        request,
                        ProcessFileForm(file_id=file.id, collection_name=knowledge_base.id),
                        user=admin_user,
                    )
                except Exception as e:
                    log.error(f"  Error processing file {file.filename} (ID: {file.id}): {str(e)}")
                    failed_files.append({"file_id": file.id, "error": str(e)})
                    continue
            
            if failed_files:
                log.warning(f"Failed to process {len(failed_files)} files in knowledge base {knowledge_base.id}")
            else:
                success_count += 1
                log.info(f"✓ Successfully reindexed knowledge base: {knowledge_base.name}")
                
        except Exception as e:
            log.error(f"Error processing knowledge base {knowledge_base.id}: {str(e)}")
            continue
    
    log.info(f"Knowledge base reindexing completed. Success: {success_count}, Deleted: {len(deleted_knowledge_bases)}")
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
        log.error("No admin user found!")
        return 0, []
    
    files = Files.get_files()
    log.info(f"Checking {len(files)} files for standalone collections")
    
    success_count = 0
    failed_files = []
    files_with_collections = 0
    
    for i, file in enumerate(files, 1):
        try:
            file_collection = f"file-{file.id}"
            
            # Check if this file has its own collection
            if VECTOR_DB_CLIENT.has_collection(collection_name=file_collection):
                files_with_collections += 1
                log.info(f"[{i}/{len(files)}] Reindexing file: {file.filename} (ID: {file.id})")
                
                # Delete old collection
                try:
                    VECTOR_DB_CLIENT.delete_collection(collection_name=file_collection)
                except Exception as e:
                    log.warning(f"Could not delete collection for {file.id}: {e}")
                    continue
                
                # Reprocess the file - collection_name=None means it will create file-{id} collection
                process_file(
                    request,
                    ProcessFileForm(file_id=file.id, collection_name=None),
                    user=admin_user
                )
                success_count += 1
                log.info(f"  ✓ Successfully reindexed")
            else:
                if i % 100 == 0:
                    log.debug(f"Checked {i}/{len(files)} files, found {files_with_collections} with collections")
                
        except Exception as e:
            log.error(f"Failed to reindex file {file.filename} (ID: {file.id}): {e}")
            failed_files.append({
                "file_id": file.id,
                "filename": file.filename,
                "error": str(e)
            })
            continue
    
    log.info(f"File reindexing complete. Total files checked: {len(files)}, With collections: {files_with_collections}, Success: {success_count}, Failed: {len(failed_files)}")
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
        log.error("No admin user found!")
        return 0, []
    
    # Get all users and then get their folders
    all_users = Users.get_users()
    log.info(f"Checking folders for {len(all_users)} users")
    
    success_count = 0
    failed_files = []
    processed_file_ids = set()  # Track processed files to avoid duplicates
    total_folders = 0
    
    for user in all_users:
        user_folders = Folders.get_folders_by_user_id(user.id)
        total_folders += len(user_folders)
        
        for folder in user_folders:
            if not folder.data or "files" not in folder.data:
                continue
            
            folder_files = folder.data.get("files", [])
            if not folder_files:
                continue
                
            log.info(f"Processing folder '{folder.name}' (user: {user.email}) with {len(folder_files)} file references")
            
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
                        log.warning(f"  File {file_id} not found, skipping")
                        continue
                    
                    file_collection = f"file-{file.id}"
                    
                    # Check if this file has its own collection
                    if VECTOR_DB_CLIENT.has_collection(collection_name=file_collection):
                        log.info(f"  Reindexing file: {file.filename} (ID: {file.id})")
                        
                        # Delete old collection
                        try:
                            VECTOR_DB_CLIENT.delete_collection(collection_name=file_collection)
                        except Exception as e:
                            log.warning(f"  Could not delete collection for {file.id}: {e}")
                            continue
                        
                        # Reprocess the file
                        process_file(
                            request,
                            ProcessFileForm(file_id=file.id, collection_name=None),
                            user=admin_user
                        )
                        success_count += 1
                        log.info(f"    ✓ Successfully reindexed")
                        
                except Exception as e:
                    log.error(f"  Failed to reindex file {file_id}: {e}")
                    failed_files.append({
                        "file_id": file_id,
                        "error": str(e)
                    })
                    continue
    
    log.info(f"Folder files reindexing complete. Total folders: {total_folders}, Unique files found: {len(processed_file_ids)}, Success: {success_count}, Failed: {len(failed_files)}")
    return success_count, failed_files


def main():
    log.info("=" * 80)
    log.info("Starting complete reindexing process")
    log.info("=" * 80)
    
    start_time = time.time()
    
    try:
        # Import and initialize the app
        log.info("Initializing Open WebUI app...")
        from open_webui.main import app
        
        # Verify we have the necessary components
        if not hasattr(app.state, 'EMBEDDING_FUNCTION'):
            log.error("App state doesn't have EMBEDDING_FUNCTION. App may not be properly initialized.")
            sys.exit(1)
        
        log.info(f"App initialized. Embedding function: {type(app.state.EMBEDDING_FUNCTION)}")
        
        # Step 1: Reindex knowledge bases
        log.info("\n" + "=" * 80)
        log.info("STEP 1: Reindexing Knowledge Bases")
        log.info("=" * 80)
        kb_success, kb_deleted = reindex_knowledge_bases(app)
        log.info(f"✓ Knowledge bases reindexed: {kb_success}, deleted: {len(kb_deleted)}")
        
        # Step 2: Reindex standalone files
        log.info("\n" + "=" * 80)
        log.info("STEP 2: Reindexing Standalone Files")
        log.info("=" * 80)
        file_success, file_failed = reindex_standalone_files(app)
        log.info(f"✓ Standalone files reindexed: {file_success}, failed: {len(file_failed)}")
        
        # Step 3: Reindex files in folders
        log.info("\n" + "=" * 80)
        log.info("STEP 3: Reindexing Files in Folders")
        log.info("=" * 80)
        folder_file_success, folder_file_failed = reindex_folder_files(app)
        log.info(f"✓ Folder files reindexed: {folder_file_success}, failed: {len(folder_file_failed)}")
        
        elapsed = time.time() - start_time
        
        log.info("\n" + "=" * 80)
        log.info("REINDEXING COMPLETE!")
        log.info("=" * 80)
        log.info(f"Total time: {elapsed:.2f} seconds ({elapsed/60:.1f} minutes)")
        log.info(f"Knowledge bases reindexed: {kb_success}")
        log.info(f"Standalone files reindexed: {file_success}")
        log.info(f"Folder files reindexed: {folder_file_success}")
        log.info(f"Total failed files: {len(file_failed) + len(folder_file_failed)}")
        
        all_failed = file_failed + folder_file_failed
        if all_failed:
            log.warning("\nFailed files:")
            for failed in all_failed[:10]:  # Show first 10
                log.warning(f"  - {failed.get('filename', 'Unknown')} ({failed['file_id']}): {failed['error']}")
            if len(all_failed) > 10:
                log.warning(f"  ... and {len(all_failed) - 10} more")
        
        log.info("\n✓ Migration from ChromaDB to pgvector is complete!")
        log.info("You can now use your Open WebUI application with pgvector.")
        
        sys.exit(0)
        
    except Exception as e:
        log.error(f"Fatal error during reindexing: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
