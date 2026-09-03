-- Allow managers to delete documents via user-scoped clients (RLS).
-- The backend delete path uses the service role and bypasses RLS, but this
-- policy keeps direct Supabase access consistent with manager permissions.

create policy "managers delete documents" on documents
  for delete using (is_manager(auth.uid()));
