import { apiRequest, csrfHeaders } from "./client";
export { ApiError } from "./client";

export interface User {
  id: number;
  name: string;
  email: string;
  created_at: string;
}

interface UserResponse {
  user: User;
}

export const authApi = {
  async register(input: { name: string; email: string; password: string }) {
    return apiRequest<{ status: "created"; user: User }>("/auth/register", {
      method: "POST",
      headers: await csrfHeaders(),
      body: JSON.stringify(input),
    });
  },

  async login(input: { email: string; password: string }) {
    return apiRequest<{ status: "ok"; user: User }>("/auth/login", {
      method: "POST",
      headers: await csrfHeaders(),
      body: JSON.stringify(input),
    });
  },

  async currentUser() {
    return apiRequest<UserResponse>("/auth/me", { cache: "no-store" });
  },

  async logout() {
    return apiRequest<{ status: "ok"; message: string }>("/auth/logout", {
      method: "POST",
      headers: await csrfHeaders(),
    });
  },
};
