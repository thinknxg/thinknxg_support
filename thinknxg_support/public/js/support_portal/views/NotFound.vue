<template>
	<section class="tx-narrow tx-center">
		<Empty icon="alert" :text="state.t('errors.not_found')">
			<a :href="link('')" data-nav class="tx-btn tx-btn--primary">{{ state.t("nav.home") }}</a>
		</Empty>
	</section>
</template>

<script setup>
import { link } from "../router";
import { state } from "../store";
import { Empty } from "../components/ui";
</script>
