import { create } from "zustand";
import type { ModelType } from "@/types/models/models";

interface ModelStoreType {
  models: ModelType[];
  modelToEdit: ModelType | undefined;
  setModels: (models: ModelType[]) => void;
  setModelToEdit: (model: ModelType | undefined) => void;
  addModel: (model: ModelType) => void;
  updateModel: (id: string, data: Partial<ModelType>) => void;
  deleteModel: (id: string) => void;
}

export const useModelStore = create<ModelStoreType>((set) => ({
  models: [],
  modelToEdit: undefined,

  setModels: (models) => set({ models }),

  setModelToEdit: (model) => set({ modelToEdit: model }),

  addModel: (model) =>
    set((state) => ({
      models: [...state.models, model],
    })),

  updateModel: (id, data) =>
    set((state) => ({
      models: state.models.map((model) =>
        model.id === id ? { ...model, ...data } : model
      ),
    })),

  deleteModel: (id) =>
    set((state) => ({
      models: state.models.filter((model) => model.id !== id),
    })),
}));