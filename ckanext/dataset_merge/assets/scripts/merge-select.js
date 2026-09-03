ckan.module("merge-select", function ($) {
  return {
    initialize() {
      $.proxyAll(this, /_/);

      this.dialog = this.$("[data-merge-select-modal]").get(0);
      this.openButton = this.$("[data-merge-select-open]");

      this.openButton.on("click", this._open);
      this.$("[data-merge-select-close]").on("click", this._close);
      this.$("[data-merge-select-form]").on("submit", (event) => event.preventDefault());
      $(this.dialog).on("close", () => this.openButton.trigger("focus"));
    },

    _open() {
      if (this.dialog.showModal) {
        this.dialog.showModal();
      } else {
        $(this.dialog).attr("open", "open");
      }

      this.$("[data-merge-select-card] input[type='search']").first().trigger("focus");
    },

    _close() {
      if (this.dialog.close) {
        this.dialog.close();
      } else {
        $(this.dialog).removeAttr("open");
        this.openButton.trigger("focus");
      }
    },
  };
});
