from app import supabase

def get_available_vendors():
    """
    Fetch all active vendors from the Supabase 'vendors' table.
    Returns:
        List of vendor dictionaries.
    """
    response = supabase.table("vendors").select("*").eq("is_active", True).execute()
    return response.data or []