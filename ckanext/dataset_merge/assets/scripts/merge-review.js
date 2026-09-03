ckan.module("merge-review", function ($) {
  return {
    initialize() {
      $.proxyAll(this, /_/);

      this.previewConfirmed = false;

      this.el.on(
        "change.mergeReview",
        '.merge-review__choice[type="radio"]',
        this._onMetadataChoice,
      );
      this.el.on(
        "change.mergeReview",
        "[data-merge-resource]",
        this._updateResources,
      );
      this.el.on(
        "click.mergeReview",
        "[data-resource-bulk]",
        this._onResourceBulk,
      );
      this.el.on(
        "click.mergeReview",
        "[data-merge-filter]",
        this._onFilter,
      );
      this.el.on(
        "click.mergeReview",
        "[data-merge-value-toggle]",
        this._onValueToggle,
      );
      this.el.on(
        "click.mergeReview",
        "[data-merge-preview-open]",
        this._openPreview,
      );
      this.el.on(
        "click.mergeReview",
        "[data-merge-preview-close]",
        this._closePreview,
      );
      this.el.on(
        "click.mergeReview",
        "[data-merge-preview-confirm]",
        this._onPreviewConfirm,
      );
      this.el.on("submit.mergeReview", this._onSubmit);

      this._initializeValueToggles();
      this._updateDecisions();
    },

    _initializeValueToggles() {
      this.el.find("[data-merge-value]").each((index, element) => {
        const value = $(element);
        const toggle = this.el.find(
          '[data-merge-value-toggle][aria-controls="' + value.attr("id") + '"]',
        );

        value.addClass("is-collapsed");
        if (element.scrollHeight > element.clientHeight) {
          toggle.prop("hidden", false);
        } else {
          value.removeClass("is-collapsed");
        }
      });
    },

    _onValueToggle(event) {
      event.preventDefault();

      const toggle = $(event.currentTarget);
      const value = this.el.find("#" + toggle.attr("aria-controls"));
      const expanded = toggle.attr("aria-expanded") === "true";

      toggle.attr("aria-expanded", expanded ? "false" : "true");
      toggle.text(expanded ? this._("Show full value") : this._("Show less"));
      value.toggleClass("is-collapsed", expanded);
    },

    _onMetadataChoice(event) {
      const field = $(event.currentTarget).closest("[data-merge-field]");

      field.find(".merge-review__value-card").each((index, card) => {
        const valueCard = $(card);
        const selected = valueCard.find(".merge-review__choice").prop("checked");
        valueCard.toggleClass("is-selected", selected);
        valueCard.find("[data-value-status]").text(selected ? this._("Kept") : this._("Not kept"));
      });

      this._updateDecisions();
    },

    _updateDecisions() {
      const conflicts = this.el.find('[data-value-state="conflict"]');
      const total = conflicts.length;
      const sourceSelected = conflicts.find('.merge-review__choice[value="source"]:checked').length;
      const bothSelected = conflicts.find('.merge-review__choice[value="both"]:checked').length;
      const baseSelected = total - sourceSelected - bothSelected;
      const progress = total ? ((sourceSelected + bothSelected) / total) * 100 : 100;

      let summary = this._("%(source)s of %(total)s conflicts use Dataset B · %(base)s use Dataset A", {
        source: sourceSelected,
        total: total,
        base: baseSelected,
      });
      if (bothSelected) {
        summary += this._(" · %(both)s combine both", {both: bothSelected});
      }

      this.el.find("[data-decision-summary]").text(summary);
      this.el.find("[data-decision-progress]").css("width", progress + "%");
    },

    _updateResources() {
      this.el.find("[data-resource-card]").each((index, card) => {
        const resource = $(card);
        const kept = resource.find("[data-merge-resource]").prop("checked");
        resource.toggleClass("is-kept", kept);

        resource.find("[data-resource-status]").text(kept ? this._("Keeping") : this._("Dropped"));
      });

      this.el.find("[data-resource-source]").each((index, group) => {
        const resourceGroup = $(group);
        const resources = resourceGroup.find("[data-merge-resource]");
        if (!resources.length) return;

        const kept = resources.filter(":checked").length;
        resourceGroup.find("[data-resource-group-summary]").text(
          this._("%(kept)s of %(total)s kept", { kept: kept, total: resources.length }),
        );
        resourceGroup.find("[data-resource-bulk]").text(
          kept === resources.length ? this._("Drop all") : this._("Keep all"),
        );
      });

      const resources = this.el.find("[data-merge-resource]");
      this.el.find("[data-resource-summary]").text(
        this._("%(kept)s of %(total)s resources kept", {
          kept: resources.filter(":checked").length,
          total: resources.length,
        }),
      );
    },

    _onResourceBulk(event) {
      const button = $(event.currentTarget);
      const resources = button.closest("[data-resource-source]").find("[data-merge-resource]");
      const keepAll = resources.filter(":checked").length !== resources.length;
      resources.prop("checked", keepAll);
      this._updateResources();
    },

    _onFilter(event) {
      const button = $(event.currentTarget);
      const filter = button.data("merge-filter");
      const fields = this.el.find("[data-merge-field]");

      this.el.find("[data-merge-filter]").removeClass("is-active").attr("aria-pressed", "false");
      button.addClass("is-active").attr("aria-pressed", "true");

      fields.each((index, field) => {
        const row = $(field);
        const state = row.data("value-state");
        const visible =
          filter === "all" ||
          (filter === "decision" && state === "conflict") ||
          (filter === "difference" && state !== "same" && state !== "empty") ||
          (filter === "unchanged" && (state === "same" || state === "empty"));
        row.prop("hidden", !visible);
      });

      this.el.find("[data-visible-fields]").text(
        this._("%(visible)s of %(total)s fields shown", {
          visible: fields.filter(":not([hidden])").length,
          total: fields.length,
        }),
      );
    },

    _onPreviewConfirm() {
      this.previewConfirmed = true;
    },

    _onSubmit(event) {
      if (this.previewConfirmed) return;

      event.preventDefault();
      this._openPreview(event);
    },

    _openPreview(event) {
      event.preventDefault();
      this._renderPreview();

      const modal = this.el.find("[data-merge-preview-modal]").get(0);
      if (!modal.open && modal.showModal) {
        modal.showModal();
      } else {
        $(modal).attr("open", "open");
      }
    },

    _closePreview(event) {
      event.preventDefault();

      const modal = this.el.find("[data-merge-preview-modal]").get(0);
      if (modal.close) {
        modal.close();
      } else {
        $(modal).removeAttr("open");
      }
    },

    _renderPreview() {
      const metadata = this.el.find("[data-merge-preview-metadata]").empty();

      this.el.find("[data-merge-field]").each((index, element) => {
        const field = $(element);
        let valueElement;

        if (field.data("value-state") === "conflict") {
          const selectedCard = field.find(".merge-review__choice:checked").closest(".merge-review__value-card");
          valueElement = selectedCard.find(".merge-review__value");
        } else if (field.hasClass("merge-review__field--automatic")) {
          valueElement = field.find(".merge-review__value");
        } else {
          valueElement = field.find(".merge-review__slim-value");
        }

        const row = $("<div>", { class: "merge-review__preview-metadata-row" });
        $("<dt>").text(field.attr("data-field-label")).appendTo(row);
        $("<dd>").text(valueElement.text().replace(/\s+/g, " ").trim()).appendTo(row);
        row.appendTo(metadata);
      });

      const resources = this.el.find("[data-merge-preview-resources]").empty();
      const selectedResources = this.el.find("[data-merge-resource]:checked");

      selectedResources.each((index, element) => {
        const card = $(element).closest("[data-resource-card]");
        const source = card.closest("[data-resource-source]").attr("data-resource-source");
        const item = $("<li>");

        $("<span>", { class: "merge-review__preview-resource-source" })
          .text(source === "base" ? this._("Dataset A") : this._("Dataset B"))
          .appendTo(item);
        const name = card.find(".merge-review__resource-name strong").text().trim();
        $("<strong>").text(name).appendTo(item);
        item.appendTo(resources);
      });

      if (!selectedResources.length) {
        $("<li>", { class: "merge-review__preview-empty" }).text(this._("No resources selected")).appendTo(resources);
      }

      this.el.find("[data-merge-preview-resource-count]").text(
        this._("%(count)s selected", { count: selectedResources.length }),
      );
    },
  };
});
