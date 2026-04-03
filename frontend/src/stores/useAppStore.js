import { create } from "zustand";
import { api } from "../services/api";

function todayString() {
  return new Date().toISOString().slice(0, 10);
}

export const useAppStore = create((set, get) => ({
  selectedDate: todayString(),
  universe: "KOSPI200",
  marketSignal: null,
  recommendations: [],
  screenerItems: [],
  history: [],
  isLoading: false,
  error: null,
  setDate: (date) => set({ selectedDate: date }),
  fetchMarketSignal: async () => {
    set({ isLoading: true, error: null });
    try {
      const selectedDate = get().selectedDate;
      const [marketSignal, history] = await Promise.all([
        api.getMarketSignal(selectedDate),
        api.getMarketSignalHistory(),
      ]);
      set({ marketSignal, history, isLoading: false });
    } catch (error) {
      set({ error: error.message, isLoading: false });
    }
  },
  fetchRecommendations: async () => {
    set({ isLoading: true, error: null });
    try {
      const selectedDate = get().selectedDate;
      const [recommendationResponse, screenerItems] = await Promise.all([
        api.getRecommendations(selectedDate),
        api.getScreener(selectedDate),
      ]);
      set({ recommendations: recommendationResponse.items, screenerItems, isLoading: false });
    } catch (error) {
      set({ error: error.message, isLoading: false });
    }
  },
  runDaily: async () => {
    set({ isLoading: true, error: null });
    try {
      await api.runDaily(get().selectedDate);
      await get().fetchMarketSignal();
      await get().fetchRecommendations();
    } catch (error) {
      set({ error: error.message, isLoading: false });
    }
  },
  reset: () => set({ error: null }),
}));

