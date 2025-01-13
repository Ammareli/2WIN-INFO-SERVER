import redis
import os
import math
from typing import List
from logger import logger


class RedisContactManager:
    def __init__(self, host='localhost', port=6379, db=0):
        """
        Initialize the Redis client.
        """
        self.redis_client = redis.Redis(host=host, port=port, db=db)
        self.contacts_key = 'contacts_set'  # Redis set to store contact IDs
        self.processing_key = 'processing_set'  # Redis set to store contacts being processed

    def store_contacts(self, clients_info):
        """
        Store contacts in Redis and add their IDs to the contacts set.
        """
        pipeline = self.redis_client.pipeline()
        for contact in clients_info:
            # Generate a unique ID for the contact
            contact_id = contact["id"]
            
            # Initialize 'message_sent' to '0'
            contact['message_sent'] = '0'
            key = f"contact:{contact_id}"
            # Store contact data
            pipeline.hset(key, mapping=contact)
            # Add contact ID to the contacts set
            pipeline.sadd(self.contacts_key, contact_id)
        pipeline.execute()
        print("Contacts have been stored in Redis and added to the contacts set.")

    def reset_all_contacts(self):
        """
        Resets 'message_sent' to '0' for all contacts, re-adds them to contacts_set, and clears processing_set.
        """
        pipeline = self.redis_client.pipeline()

        # Reset 'message_sent' and re-add contact IDs to contacts_set
        contact_keys = self.redis_client.keys('contact:*')
        for key in contact_keys:
            # Reset 'message_sent' to '0'
            pipeline.hset(key, 'message_sent', '0')
            # Extract contact_id from the key
            contact_id = key.decode('utf-8').split(':', 1)[1]
            # Re-add contact_id to contacts_set
            pipeline.sadd(self.contacts_key, contact_id)

        # Clear the processing_set
        pipeline.delete(self.processing_key)

        pipeline.execute()
        print("All contacts have been reset and re-queued. processing_set has been cleared.")
    
    def delete_contact_by_id(self, contact_id):
        """
        Deletes a contact from Redis by contact ID.

        Args:
            contact_id (str): The ID of the contact.
        """
        key = f"contact:{contact_id}"
        pipeline = self.redis_client.pipeline()
        # Delete the contact hash
        pipeline.delete(key)
        # Remove from contacts_set
        pipeline.srem(self.contacts_key, contact_id)
        # Remove from processing_set if present
        pipeline.srem(self.processing_key, contact_id)
        pipeline.execute()
        logger.info(f"Contact with ID {contact_id} deleted from Redis.")



    def delete_all_contacts(self):
        """
        Delete all contacts from Redis.
        """
        pipeline = self.redis_client.pipeline()

        # Delete contact hashes
        keys = self.redis_client.keys('contact:*')
        if keys:
            pipeline.delete(*keys)
            print("All contact hashes have been deleted.")
        else:
            print("No contact hashes to delete.")

        # Delete the contacts set
        pipeline.delete(self.contacts_key)
        # Delete the processing set
        pipeline.delete(self.processing_key)
        pipeline.execute()
        print("Contacts set and processing set have been deleted.")

    def flushDB(self):
        """
        Delete everything from the current Redis database.
        This method will remove all keys and data from Redis.
        """
        try:
            self.redis_client.flushdb()
            print("All data in the Redis database has been deleted.")
        except Exception as e:
            print(f"Failed to delete data from Redis: {e}")
            
    def get_all_contacts(self):
        """
        Retrieve all contacts from Redis.
        """
        keys = self.redis_client.keys('contact:*')
        contacts = []
        for key in keys:
            contact_data = self.redis_client.hgetall(key)
            # Convert bytes to appropriate data types
            contact = {k.decode('utf-8'): self._decode_value(v) for k, v in contact_data.items()}
            contacts.append(contact)
        return contacts


    def _decode_value(self, value):
        """
        Decode Redis bytes value to appropriate Python data type.
        """
        try:
            return value.decode('utf-8')
        except UnicodeDecodeError:
            return value

    def acquire_lock(self, lock_name, timeout=60):
        """
        Acquire a Redis lock to prevent concurrent processing.
        """
        lock = self.redis_client.lock(lock_name, timeout=timeout)
        acquired = lock.acquire(blocking=False)
        if acquired:
            print(f"Lock {lock_name} acquired.")
        else:
            print(f"Lock {lock_name} is already held.")
        return lock if acquired else None

    def release_lock(self, lock):
        """
        Release a previously acquired Redis lock.
        """
        lock.release()
        print(f"Lock {lock.name} released.")

    def get_contact_by_id(self, contact_id):
        """
        Retrieves the contact information by contact ID from Redis.

        Args:
            contact_id (str): The ID of the contact.

        Returns:
            dict: The contact information if found, None otherwise.
        """
        key = f"contact:{contact_id}"
        contact_data = self.redis_client.hgetall(key)
        if contact_data:
            # Decode the bytes to strings
            contact = {k.decode('utf-8'): self._decode_value(v) for k, v in contact_data.items()}
            # Include the contact ID in the returned data
            contact['id'] = contact_id
            return contact
        else:
            return None

